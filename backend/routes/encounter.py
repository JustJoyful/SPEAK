import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Body
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
        # Publish checklist state to the global event bus for SSE
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
