"""Local SQLite database interface for MedSync edge node."""

import os
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "medsync_edge.db")


_initialized_dbs = set()


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes local tables: queue, care_contexts, encounters, and hash_chain."""
    path = db_path or SQLITE_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Reception Patient Queue (Decoupled Identity Flow)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS queue (
        token_number INTEGER PRIMARY KEY,
        care_context_id TEXT NOT NULL,
        patient_display_name TEXT NOT NULL,
        abha_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'waiting', -- waiting | in-progress | done
        is_locked INTEGER NOT NULL DEFAULT 0,
        cumulative_transcript TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Care-Context Mapping (STRICTLY LOCAL, never leaves edge node)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS care_contexts (
        care_context_id TEXT PRIMARY KEY,
        raw_abha_id TEXT NOT NULL,
        abha_hash TEXT NOT NULL,
        clinic_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Index on abha_hash for quick local re-association lookup
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_care_contexts_abha_hash 
    ON care_contexts(abha_hash);
    """)

    # 3. Local Encrypted Encounters (Zero-Trust AES-256-GCM storage)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS encounters (
        bundle_id TEXT PRIMARY KEY,
        care_context_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        nonce TEXT NOT NULL,
        tag TEXT NOT NULL,
        record_hash TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        synced_to_central INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (care_context_id) REFERENCES care_contexts(care_context_id)
    );
    """)

    # 4. Hash Chain Ledger (Tamper-evident verification chain)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hash_chain (
        block_index INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id TEXT NOT NULL,
        record_hash TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    _initialized_dbs.add(path)


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Creates a connection with row factory enabled and auto-ensures schema exists."""
    path = db_path or SQLITE_DB_PATH
    if path not in _initialized_dbs:
        init_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------
# Reception & Queue DB Helpers
# ---------------------------------------------------------

def enqueue_patient(
    token_number: int,
    care_context_id: str,
    patient_display_name: str,
    abha_hash: str,
    status: str = "waiting",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Add a patient to the daily queue."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO queue (token_number, care_context_id, patient_display_name, abha_hash, status, is_locked, cumulative_transcript)
        VALUES (?, ?, ?, ?, ?, 0, '')
        ON CONFLICT(token_number) DO UPDATE SET
            care_context_id=excluded.care_context_id,
            patient_display_name=excluded.patient_display_name,
            abha_hash=excluded.abha_hash,
            status=excluded.status
        """,
        (token_number, care_context_id, patient_display_name, abha_hash, status)
    )
    conn.commit()
    conn.close()
    return {
        "token_number": token_number,
        "care_context_id": care_context_id,
        "patient_display_name": patient_display_name,
        "abha_hash": abha_hash,
        "status": status
    }


def get_daily_queue(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all entries from today's patient queue."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM queue ORDER BY token_number ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_queue_entry_by_token(token_number: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a specific queue token entry."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM queue WHERE token_number = ?", (token_number,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_token_status(token_number: int, status: str, db_path: Optional[str] = None) -> bool:
    """Update patient token status (waiting -> in-progress -> done)."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE queue SET status = ? WHERE token_number = ?",
        (status, token_number)
    )
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0


def seed_demo_queue(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Pre-seed 3-4 realistic mock patients for hackathon demo."""
    import hashlib
    import hmac

    salt = os.getenv("ABDM_SALT", "medsync-sih-2026-edge-node-salt-secret").encode()

    def make_hash(abha_id: str) -> str:
        return hmac.new(salt, abha_id.encode(), hashlib.sha256).hexdigest()

    demo_patients = [
        {
            "token": 1,
            "name": "Priya Sharma",
            "abha": "91-4820-9182-4412",
            "context": "CC-90142"
        },
        {
            "token": 2,
            "name": "Rahul Verma",
            "abha": "14-9912-3841-7782",
            "context": "CC-81203"
        },
        {
            "token": 3,
            "name": "Ananya Mukherjee",
            "abha": "88-1204-5519-3321",
            "context": "CC-73019"
        },
        {
            "token": 4,
            "name": "Vikram Patel",
            "abha": "52-6619-2041-8890",
            "context": "CC-64821"
        }
    ]

    for p in demo_patients:
        h = make_hash(p["abha"])
        insert_care_context(p["context"], p["abha"], h, "CLINIC-01", db_path)
        enqueue_patient(p["token"], p["context"], p["name"], h, "waiting", db_path)

    return get_daily_queue(db_path)


# ---------------------------------------------------------
# Local DB Helper Queries
# ---------------------------------------------------------

def insert_care_context(
    care_context_id: str,
    raw_abha_id: str,
    abha_hash: str,
    clinic_id: str,
    db_path: Optional[str] = None
) -> None:
    """Store local care context mapping."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO care_contexts (care_context_id, raw_abha_id, abha_hash, clinic_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(care_context_id) DO UPDATE SET
            raw_abha_id=excluded.raw_abha_id,
            abha_hash=excluded.abha_hash,
            clinic_id=excluded.clinic_id
        """,
        (care_context_id, raw_abha_id, abha_hash, clinic_id)
    )
    conn.commit()
    conn.close()


def get_care_context_by_id(care_context_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch care context mapping for re-identification on local doctor screen."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM care_contexts WHERE care_context_id = ?",
        (care_context_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def insert_encounter(
    bundle_id: str,
    care_context_id: str,
    payload: str,
    nonce: str,
    tag: str,
    record_hash: str,
    prev_hash: str,
    db_path: Optional[str] = None
) -> None:
    """Persist an encrypted encounter."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO encounters 
        (bundle_id, care_context_id, payload, nonce, tag, record_hash, prev_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (bundle_id, care_context_id, payload, nonce, tag, record_hash, prev_hash)
    )
    conn.commit()
    conn.close()


def get_latest_hash_from_chain(db_path: Optional[str] = None) -> str:
    """Fetch previous hash or genesis hash (64 zeros) for the hash chain."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT record_hash FROM hash_chain ORDER BY block_index DESC LIMIT 1"
    )
    row = cursor.fetchone()
    conn.close()
    return row["record_hash"] if row else "0" * 64


def append_to_hash_chain(
    record_id: str,
    record_hash: str,
    prev_hash: str,
    db_path: Optional[str] = None
) -> int:
    """Append new record link to the local tamper-evident hash chain."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO hash_chain (record_id, record_hash, prev_hash)
        VALUES (?, ?, ?)
        """,
        (record_id, record_hash, prev_hash)
    )
    conn.commit()
    block_index = cursor.lastrowid
    conn.close()
    return block_index or 0

def update_session_lock(token_number: int, is_locked: bool, db_path: Optional[str] = None) -> bool:
    """Lock or unlock a patient session."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE queue SET is_locked = ? WHERE token_number = ?",
        (1 if is_locked else 0, token_number)
    )
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0


def update_session_transcript(token_number: int, transcript: str, is_locked: bool, db_path: Optional[str] = None) -> bool:
    """Update cumulative transcript for a patient session."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE queue SET cumulative_transcript = ?, is_locked = ? WHERE token_number = ?",
        (transcript, 1 if is_locked else 0, token_number)
    )
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0
