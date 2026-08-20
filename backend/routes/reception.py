"""Reception API Routes: Identity resolution, token enqueuing, and daily queue management."""

import os
import uuid
import hmac
import hashlib
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.pipeline.fhir_schema import QueueEntry
from backend.pipeline.care_context import create_and_store_care_context
from backend.db.local import (
    enqueue_patient,
    get_daily_queue,
    seed_demo_queue,
    update_token_status
)

router = APIRouter(prefix="/queue", tags=["Reception & Queue"])


class EnqueuePatientRequest(BaseModel):
    patient_display_name: str = Field(..., example="Priya Sharma")
    raw_abha_id: str = Field(..., example="91-4820-9182-4412", description="Raw 14-digit ABHA ID or mobile number")
    clinic_id: str = Field(default="CLINIC-01")


@router.get("/today", response_model=List[Dict[str, Any]])
async def get_today_queue():
    """Retrieve today's active patient queue for the doctor sidebar."""
    queue = get_daily_queue()
    if not queue:
        # Automatically seed if queue is currently empty for seamless demo experience
        queue = seed_demo_queue()
    return queue


@router.post("/seed", response_model=List[Dict[str, Any]])
async def seed_queue():
    """Reset and pre-seed 4 realistic mock patients for hackathon demo."""
    return seed_demo_queue()


@router.post("/add")
async def add_patient_to_queue(req: EnqueuePatientRequest):
    """Reception Desk Endpoint:
    
    1. Generates salted HMAC-SHA256 hash of the patient's ABHA ID.
    2. Issues a local CareContext ID (e.g., CC-98124).
    3. Persists identity mapping strictly in local SQLite.
    4. Enqueues patient with the next sequential token number.
    """
    # 1. Create CareContext, hash ABHA ID, and save strictly local identity mapping
    ctx = create_and_store_care_context(
        raw_abha_id=req.raw_abha_id.strip(),
        clinic_id=req.clinic_id
    )
    care_context_id = ctx["care_context_id"]
    abha_hash = ctx["abha_hash"]

    # 2. Determine next token number
    current_queue = get_daily_queue()
    next_token = max([q["token_number"] for q in current_queue], default=0) + 1

    # 3. Add to daily queue
    entry = enqueue_patient(
        token_number=next_token,
        care_context_id=care_context_id,
        patient_display_name=req.patient_display_name.strip(),
        abha_hash=abha_hash,
        status="waiting"
    )

    return {
        "status": "success",
        "message": "Patient enqueued successfully with zero cloud identity leakage",
        "queue_entry": entry
    }


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="waiting | in-progress | done")


@router.patch("/{token_number}/status")
async def update_status(token_number: int, req: UpdateStatusRequest):
    """Update patient token status."""
    if req.status not in ["waiting", "in-progress", "done"]:
        raise HTTPException(status_code=400, detail="Invalid status. Must be 'waiting', 'in-progress', or 'done'.")
    
    success = update_token_status(token_number, req.status)
    if not success:
        raise HTTPException(status_code=404, detail=f"Token #{token_number} not found.")
    
    return {"status": "success", "token_number": token_number, "new_status": req.status}
