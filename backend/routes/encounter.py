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

    from backend.pipeline.stt import get_stt_engine, build_clinical_prompt
    import numpy as np

    stt = get_stt_engine()  # lazy singleton — model loads on first WS connection
    raw_buffer = b""
    speech_chunks = []
    buffered_speech_samples = 0
    trailing_silence_samples = 0

    SAMPLE_RATE = 16000
    MIN_SPEECH_SAMPLES = int(0.6 * SAMPLE_RATE)    # At least 600ms of speech before triggering on pause
    MAX_SPEECH_SAMPLES = int(3.5 * SAMPLE_RATE)    # Max 3.5s phrase before auto-transcribing
    PAUSE_SILENCE_SAMPLES = int(0.4 * SAMPLE_RATE) # 400ms pause triggers sentence boundary
    SLICE_BYTES = 8000                             # 250ms audio slice (4000 samples)

    # Look up patient context to condition Whisper decoder for high phonetic accuracy
    entry = get_queue_entry_by_token(token_number)
    patient_name = entry.get("patient_display_name", "") if entry else ""
    complaint = entry.get("chief_complaint", "") if entry else ""
    clinical_prompt = build_clinical_prompt(patient_name, complaint)

    try:
        while True:
            data = await websocket.receive_bytes()
            raw_buffer += data

            # Process in 250ms chunks (8,000 bytes) for fine-grained VAD and phrase accumulation
            while len(raw_buffer) >= SLICE_BYTES:
                slice_data = raw_buffer[:SLICE_BYTES]
                raw_buffer = raw_buffer[SLICE_BYTES:]

                chunk_np = np.frombuffer(slice_data, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(chunk_np ** 2)))
                is_speech = rms >= 0.0025

                should_transcribe = False
                if is_speech:
                    trailing_silence_samples = 0
                    speech_chunks.append(chunk_np)
                    buffered_speech_samples += len(chunk_np)
                    if buffered_speech_samples >= MAX_SPEECH_SAMPLES:
                        should_transcribe = True
                else:
                    if buffered_speech_samples >= MIN_SPEECH_SAMPLES:
                        trailing_silence_samples += len(chunk_np)
                        speech_chunks.append(chunk_np)
                        buffered_speech_samples += len(chunk_np)
                        if trailing_silence_samples >= PAUSE_SILENCE_SAMPLES:
                            should_transcribe = True
                    else:
                        # Clear stray noise / clicks when not part of sustained speech
                        speech_chunks.clear()
                        buffered_speech_samples = 0
                        trailing_silence_samples = 0

                if should_transcribe and speech_chunks:
                    full_audio_np = np.concatenate(speech_chunks)
                    speech_chunks.clear()
                    buffered_speech_samples = 0
                    trailing_silence_samples = 0

                    text = await asyncio.to_thread(stt.transcribe_segment, full_audio_np, clinical_prompt)
                    if not text:
                        continue

                    active_session.append_transcript(token_number, text)

                    # Regex-only PII pass during live dictation — fast (<1ms)
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
            flush_list = list(speech_chunks)
            if len(raw_buffer) >= 3200:
                aligned_len = len(raw_buffer) - (len(raw_buffer) % 2)
                flush_list.append(np.frombuffer(raw_buffer[:aligned_len], dtype=np.int16).astype(np.float32) / 32768.0)
            if flush_list:
                full_audio_np = np.concatenate(flush_list)
                if len(full_audio_np) >= int(0.3 * SAMPLE_RATE):
                    text = await asyncio.to_thread(stt.transcribe_segment, full_audio_np, clinical_prompt)
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
