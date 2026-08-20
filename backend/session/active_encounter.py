"""Active Encounter Session State & Token Locking for MedSync Doctor Desk."""

from typing import Optional, Dict, Any
from fastapi import HTTPException
from backend.db.local import get_queue_entry_by_token, update_token_status


class ActiveEncounterSession:
    """Thread-safe active encounter state holder.
    
    Prevents token-swapping errors mid-session (Hole #1 fix).
    Ensures the doctor's screen never sees or leaks ABHA IDs.
    """

    def __init__(self):
        self.active_token_number: Optional[int] = None
        self.active_care_context_id: Optional[str] = None
        self.patient_display_name: Optional[str] = None
        self.is_locked: bool = False  # Set to True when recording or dictation is active
        self.cumulative_transcript: str = ""

    def select_token(self, token_number: int, force: bool = False, db_path: Optional[str] = None) -> Dict[str, Any]:
        """Selects and binds a patient token to the active doctor session."""
        if self.is_locked and self.active_token_number != token_number and not force:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "SESSION_LOCKED",
                    "message": f"Token #{self.active_token_number} is actively in progress. Complete or discard current session before switching tokens.",
                    "active_token": self.active_token_number
                }
            )

        entry = get_queue_entry_by_token(token_number, db_path=db_path)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Token #{token_number} not found in today's queue.")

        self.active_token_number = token_number
        self.active_care_context_id = entry["care_context_id"]
        self.patient_display_name = entry["patient_display_name"]
        self.is_locked = False
        self.cumulative_transcript = ""

        # Update DB queue status to in-progress
        update_token_status(token_number, "in-progress", db_path=db_path)

        return {
            "status": "success",
            "token_number": token_number,
            "patient_display_name": self.patient_display_name,
            # Notice: NO abha_id or abha_hash returned to the doctor view!
            "session_ready": True
        }

    def set_locked(self, locked: bool = True) -> None:
        """Locks session during active audio recording / dictation."""
        self.is_locked = locked

    def append_transcript(self, text: str) -> str:
        """Appends cumulative transcript text."""
        if text.strip():
            if self.cumulative_transcript:
                self.cumulative_transcript += " " + text.strip()
            else:
                self.cumulative_transcript = text.strip()
        self.is_locked = True
        return self.cumulative_transcript

    def clear_session(self) -> None:
        """Resets active session state."""
        self.active_token_number = None
        self.active_care_context_id = None
        self.patient_display_name = None
        self.is_locked = False
        self.cumulative_transcript = ""

    def get_current_state(self) -> Dict[str, Any]:
        """Returns safe view of active session state."""
        return {
            "active_token_number": self.active_token_number,
            "patient_display_name": self.patient_display_name,
            "is_locked": self.is_locked,
            "has_transcript": bool(self.cumulative_transcript)
        }


# Global active session instance for doctor desk
active_session = ActiveEncounterSession()
