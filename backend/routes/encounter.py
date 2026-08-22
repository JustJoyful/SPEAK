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

router = APIRouter(
    prefix="/encounter",
    tags=["Doctor Encounter"],
    dependencies=[Depends(verify_doctor)]
)

@router.post("/{token_number}/select")
async def select_patient(token_number: int):
    """Doctor selects a patient from the queue."""
    result = active_session.select_token(token_number)
    event_bus.log_audit_event("SELECT_PATIENT", f"Token {token_number} selected.", "Doctor")
    return result

@router.post("/{token_number}/transcript")
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

@router.get("/{token_number}/checklist/stream")
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
async def stream_audio(websocket: WebSocket, token_number: int):
    await websocket.accept()
    from backend.pipeline.stt import stt_engine
    from backend.pipeline.pii_mask import mask_pii
    import numpy as np
    
    buffer = b""
    try:
        while True:
            data = await websocket.receive_bytes()
            buffer += data
            
            # 16000 Hz, 16-bit PCM = 32000 bytes per second
            # Process every 1 second of audio (32000 bytes)
            if len(buffer) >= 32000:
                # Ensure 16-bit int alignment (2 bytes per sample)
                aligned_len = len(buffer) - (len(buffer) % 2)
                chunk = buffer[:aligned_len]
                buffer = buffer[aligned_len:]
                
                audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                
                # VAD detection
                timestamps = stt_engine.get_speech_timestamps(audio_np)
                
                if timestamps:
                    # Speech detected, transcribe segment
                    text = stt_engine.transcribe_segment(audio_np)
                    if text:
                        # Append to global transcript
                        active_session.append_transcript(token_number, text)
                        
                        # Trap C: Mask PII before sending back
                        mask_result = mask_pii(text)
                        
                        # Also get checklist update
                        cumulative = active_session.get_current_state(token_number).get("transcript", "")
                        checklist, _ = await extract_checklist(cumulative)
                        
                        await websocket.send_json({
                            "type": "TRANSCRIPT_CHUNK",
                            "text": mask_result["sanitized_text"],
                            "ui_toggles": checklist.model_dump() if checklist else {}
                        })
                
    except WebSocketDisconnect:
        try:
            if len(buffer) >= 3200: # at least 0.1s
                aligned_len = len(buffer) - (len(buffer) % 2)
                chunk = buffer[:aligned_len]
                audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                if stt_engine.get_speech_timestamps(audio_np):
                    text = stt_engine.transcribe_segment(audio_np)
                    if text:
                        active_session.append_transcript(token_number, text)
                        mask_result = mask_pii(text)
                        await websocket.send_json({
                            "type": "TRANSCRIPT_CHUNK",
                            "text": mask_result["sanitized_text"],
                            "ui_toggles": {}
                        })
        except Exception:
            pass

@router.post("/{token_number}/finalize")
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

@router.get("/{token_number}/record")
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
