import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from typing import Dict, Any

from backend.routes.auth_deps import verify_doctor
from backend.session.active_encounter import active_session
from backend.pipeline.checklist import extract_checklist
from backend.events.bus import event_bus
from backend.pipeline.llm_structurer import sadiesink
from backend.pipeline.crypto import encrypt_fhir_bundle
from backend.db.local import get_queue_entry_by_token, update_token_status
from backend.pipeline.pii_mask import global_pii_masker

router = APIRouter(
    prefix="/encounter",
    tags=["Doctor Encounter"],
    # NOTE: Router-level dependencies are NOT used here because they also apply to
    # WebSocket routes, and the browser WebSocket API cannot send custom headers.
    # Instead, verify_doctor is applied per HTTP endpoint, and the WebSocket
    # authenticates via a ?role= query parameter.
)

@router.post("/{token_number}/select", dependencies=[Depends(verify_doctor)])
async def select_patient(token_number: int):
    """Doctor selects a patient from the queue."""
    result = active_session.select_token(token_number)
    event_bus.log_audit_event("SELECT_PATIENT", f"Token {token_number} selected.", "Doctor")
    return result

@router.post("/{token_number}/transcript", dependencies=[Depends(verify_doctor)])
async def append_transcript(token_number: int, data: Dict[str, str] = Body(...)):
    """Receives partial transcript from the frontend (STT)."""
    text = data.get("text", "")
    cumulative_text = active_session.append_transcript(token_number, text)
    
    # Run the lightweight checklist extraction pipeline
    checklist, error = await extract_checklist(cumulative_text)
    if not error and checklist:
        # Publish checklist state to the checklist SSE channel and the global event bus
        await event_bus.publish(f"checklist_{token_number}", checklist.model_dump())
        await event_bus.publish("global", {"checklist": checklist.model_dump()})
        
    return {"status": "success", "cumulative_length": len(cumulative_text)}

@router.get("/{token_number}/checklist/stream", dependencies=[Depends(verify_doctor)])
async def stream_checklist(token_number: int):
    """SSE endpoint for streaming checklist updates to the frontend."""
    async def event_generator():
        q = event_bus.subscribe(f"checklist_{token_number}")
        try:
            while True:
                data = await q.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            event_bus.unsubscribe(f"checklist_{token_number}", q)
            raise
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/{token_number}/audio-stream")
async def stream_audio(websocket: WebSocket, token_number: int, role: str = ""):
    """
    Receive raw PCM int16 audio at 16 kHz mono and stream back transcript chunks.

    Authentication: The browser WebSocket API cannot send custom headers, so role
    is passed as a query parameter (?role=doctor) by the frontend instead.
    """
    if role.lower() != "doctor":
        await websocket.close(code=1008, reason="Forbidden: Doctor role required")
        return
    await websocket.accept()

    from backend.pipeline.stt import get_stt_engine
    from backend.pipeline.pii_mask import mask_pii
    import numpy as np

    stt = get_stt_engine()  # lazy singleton — model loads on first WS connection
    buffer = b""

    try:
        while True:
            data = await websocket.receive_bytes()
            buffer += data

            # 16 000 Hz × 2 bytes (int16) = 32 000 bytes per second.
            # Process in 1-second chunks to balance latency vs. transcription quality.
            if len(buffer) >= 32000:
                aligned_len = len(buffer) - (len(buffer) % 2)
                chunk, buffer = buffer[:aligned_len], buffer[aligned_len:]

                audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0

                if not stt.has_speech(audio_np):
                    continue  # Silence — skip Whisper, avoid hallucinations

                text = stt.transcribe_segment(audio_np)
                if not text:
                    continue

                active_session.append_transcript(token_number, text)

                # Regex-only PII pass during live dictation — fast (<1ms) and avoids
                # loading GLiNER (500MB) while Whisper is already in RAM.
                # Full GLiNER masking happens at finalize before any cloud egress.
                regex_spans = global_pii_masker._regex_pass(text)
                display_text = text
                for span in sorted(regex_spans, key=lambda s: s["start"], reverse=True):
                    display_text = display_text[:span["start"]] + span["replacement"] + display_text[span["end"]:]

                state = active_session.get_current_state(token_number)
                cumulative = state.get("transcript", "")
                checklist, _ = await extract_checklist(cumulative)

                await websocket.send_json({
                    "type": "TRANSCRIPT_CHUNK",
                    "text": display_text,
                    "ui_toggles": checklist.model_dump() if checklist else {}
                })

    except WebSocketDisconnect:
        # Flush any remaining audio in the buffer on clean disconnect
        try:
            if len(buffer) >= 3200:  # at least 0.1 s
                aligned_len = len(buffer) - (len(buffer) % 2)
                audio_np = np.frombuffer(buffer[:aligned_len], dtype=np.int16).astype(np.float32) / 32768.0
                if stt.has_speech(audio_np):
                    text = stt.transcribe_segment(audio_np)
                    if text:
                        active_session.append_transcript(token_number, text)
        except Exception:  # noqa: BLE001
            pass  # Best-effort flush — don't crash on disconnect

@router.post("/{token_number}/finalize", dependencies=[Depends(verify_doctor)])
async def finalize_encounter(token_number: int):
    """Finalizes the encounter, structuring the note and encrypting it."""
    state = active_session.get_current_state(token_number)
    entry = get_queue_entry_by_token(token_number)
    
    if not entry or not state["has_transcript"]:
        raise HTTPException(status_code=400, detail="Cannot finalize without a transcript.")
        
    cumulative_text = entry["cumulative_transcript"]
    care_context_id = entry["care_context_id"]
    
    # Run PII masking (Zero-Trust edge masking before Cloud LLM)
    from backend.pipeline.pii_mask import mask_pii
    mask_result = mask_pii(cumulative_text)
    sanitized_text = mask_result["sanitized_text"]
    
    if mask_result["pii_detected"]:
        event_bus.log_audit_event("PII_MASKED", f"Redacted entities: {mask_result['entity_counts']}", "System")
        
    await event_bus.publish("global", {
        "stage": "PII",
        "level": "redact" if mask_result["pii_detected"] else "info",
        "message": f"Masked {sum(mask_result['entity_counts'].values())} sensitive entities" if mask_result["pii_detected"] else "No sensitive entities found",
        "redacted": mask_result["pii_detected"]
    })
        
    # Overwrite cumulative_transcript with sanitized text for offline storage
    from backend.db.local import update_session_transcript, update_sync_status
    update_session_transcript(token_number, sanitized_text, is_locked=False)
    
    # Mark queue as done from doctor's view, and sync_status as pending_structuring
    update_token_status(token_number, "done")
    update_sync_status(token_number, "pending_structuring")
    active_session.clear_session(token_number)
    
    await event_bus.publish("global", {
        "stage": "QUEUE",
        "level": "info",
        "message": f"Session {token_number} moved to sync queue"
    })
    
    event_bus.log_audit_event("FINALIZE_ENCOUNTER", f"Token {token_number} finalized locally, pending sync.", "Doctor")
    
    return {
        "status": "success",
        "message": "Encounter finalized locally and queued for secure sync.",
        "sync_status": "pending_structuring"
    }

@router.get("/{token_number}/record", dependencies=[Depends(verify_doctor)])
async def get_encounter_record(token_number: int):
    """Fetches the decrypted, structured record if it has been synced."""
    entry = get_queue_entry_by_token(token_number)
    if not entry:
        raise HTTPException(status_code=404, detail="Token not found.")
        
    if entry["sync_status"] not in ["structured", "synced"]:
        raise HTTPException(status_code=423, detail="Record is still being processed. Please wait a moment.")
        
    from backend.db.local import get_encounter_by_care_context
    encounter = get_encounter_by_care_context(entry["care_context_id"])
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter record not found.")
        
    from backend.pipeline.crypto import decrypt_payload
    try:
        decrypted_json = decrypt_payload(encounter["payload"], encounter["nonce"], encounter["tag"])
        return json.loads(decrypted_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt record: {e}")
