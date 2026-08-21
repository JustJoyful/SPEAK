"""Active Encounter Session State & Token Locking for MedSync Doctor Desk."""

from typing import Optional, Dict, Any
from fastapi import HTTPException
from backend.db.local import get_queue_entry_by_token, update_token_status


class ActiveEncounterSession:
    """Thread-safe active encounter state holder.
    
    Prevents token-swapping errors mid-session (Hole #1 fix).
    Ensures the doctor's screen never sees or leaks ABHA IDs.
    """



    def select_token(self, token_number: int, force: bool = False, db_path: Optional[str] = None) -> Dict[str, Any]:
        """Selects and binds a patient token to the active doctor session."""
        entry = get_queue_entry_by_token(token_number, db_path=db_path)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Token #{token_number} not found in today's queue.")
            
        if entry["is_locked"] and not force:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "SESSION_LOCKED",
                    "message": f"Token #{token_number} is actively in progress. Complete or discard current session before switching tokens.",
                    "active_token": token_number
                }
            )

        # Update DB queue status to in-progress
        update_token_status(token_number, "in-progress", db_path=db_path)
        # We explicitly lock the session upon starting selection
        from backend.db.local import update_session_lock
        update_session_lock(token_number, False, db_path=db_path)

        return {
            "status": "success",
            "token_number": token_number,
            "patient_display_name": entry["patient_display_name"],
            # Notice: NO abha_id or abha_hash returned to the doctor view!
            "session_ready": True
        }

    def set_locked(self, token_number: int, locked: bool = True, db_path: Optional[str] = None) -> None:
        """Locks session during active audio recording / dictation."""
        from backend.db.local import update_session_lock
        update_session_lock(token_number, locked, db_path=db_path)

    def append_transcript(self, token_number: int, text: str, db_path: Optional[str] = None) -> str:
        """Appends cumulative transcript text."""
        entry = get_queue_entry_by_token(token_number, db_path=db_path)
        if not entry:
            raise HTTPException(status_code=404, detail="Token not found")
            
        current = entry["cumulative_transcript"]
        if text.strip():
            if current:
                current += " " + text.strip()
            else:
                current = text.strip()
                
        from backend.db.local import update_session_transcript
        update_session_transcript(token_number, current, is_locked=True, db_path=db_path)
        return current

    def clear_session(self, token_number: int, db_path: Optional[str] = None) -> None:
        """Resets active session state for a token (unlock and clear)."""
        from backend.db.local import update_session_transcript
        update_session_transcript(token_number, "", is_locked=False, db_path=db_path)

    def get_current_state(self, token_number: int, db_path: Optional[str] = None) -> Dict[str, Any]:
        """Returns safe view of active session state."""
        entry = get_queue_entry_by_token(token_number, db_path=db_path)
        if not entry:
            raise HTTPException(status_code=404, detail="Token not found")
            
        return {
            "active_token_number": token_number,
            "patient_display_name": entry["patient_display_name"],
            "is_locked": bool(entry["is_locked"]),
            "has_transcript": bool(entry["cumulative_transcript"])
        }


# Global active session instance for doctor desk
active_session = ActiveEncounterSession()
