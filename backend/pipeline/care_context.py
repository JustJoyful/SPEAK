import hashlib
import hmac
import os
import random
from typing import Dict, Any, Optional

from backend.db.local import insert_care_context, get_care_context_by_id

DEFAULT_SALT = os.getenv("ABDM_SALT", "medsync-sih-2026-edge-node-salt-secret")


def generate_abha_hash(raw_abha_id: str, salt: Optional[str] = None) -> str:
    """Generate deterministic salted HMAC-SHA256 hash for an ABHA ID."""
    used_salt = (salt or DEFAULT_SALT).encode('utf-8')
    return hmac.new(used_salt, raw_abha_id.encode('utf-8'), hashlib.sha256).hexdigest()


def generate_care_context_id() -> str:
    """Generate a local care context ID in the format CC-XXXXXX."""
    return f"CC-{random.randint(100000, 999999)}"


def create_and_store_care_context(
    raw_abha_id: str, 
    clinic_id: str, 
    salt: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a new care context, hashes the ABHA ID, stores it in the local edge DB,
    and returns the care context details.
    """
    abha_hash = generate_abha_hash(raw_abha_id, salt)
    care_context_id = generate_care_context_id()
    
    insert_care_context(
        care_context_id=care_context_id,
        raw_abha_id=raw_abha_id,
        abha_hash=abha_hash,
        clinic_id=clinic_id,
        db_path=db_path
    )
    
    return {
        "care_context_id": care_context_id,
        "raw_abha_id": raw_abha_id,
        "abha_hash": abha_hash,
        "clinic_id": clinic_id
    }


def resolve_care_context(care_context_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Resolves a care context ID to its underlying de-anonymized data from local SQLite.
    """
    return get_care_context_by_id(care_context_id, db_path=db_path)
