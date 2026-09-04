"""Local SQLite database interface for MedSync edge node."""

import os
import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "medsync_edge.db")

_initialized_dbs = set()


def _configure_connection(conn: sqlite3.Connection) -> None:
    """Configures connection pragmas for high concurrency and resilience."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes local tables: queue, care_contexts, encounters, and hash_chain."""
    path = db_path or SQLITE_DB_PATH
    conn = sqlite3.connect(path, timeout=20.0)
    _configure_connection(conn)
    cursor = conn.cursor()

    # 1. Reception Patient Queue (Decoupled Identity Flow)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS queue (
        token_number INTEGER PRIMARY KEY,
        care_context_id TEXT NOT NULL,
        patient_display_name TEXT NOT NULL,
        abha_hash TEXT NOT NULL,
        age INTEGER,
        sex TEXT,
        chief_complaint TEXT,
        script TEXT,
        marks_json TEXT,
        pii_json TEXT,
        fhir_preview_json TEXT,
        status TEXT NOT NULL DEFAULT 'waiting', -- waiting | in-progress | done
        sync_status TEXT NOT NULL DEFAULT 'none', -- none | pending_structuring | structured | encrypted_stored | synced
        is_locked INTEGER NOT NULL DEFAULT 0,
        cumulative_transcript TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Column upgrade checks for existing databases
    existing_cols = {col[1] for col in cursor.execute("PRAGMA table_info(queue)").fetchall()}
    for col_name, col_def in [
        ("age", "INTEGER"),
        ("sex", "TEXT"),
        ("chief_complaint", "TEXT"),
        ("script", "TEXT"),
        ("marks_json", "TEXT"),
        ("pii_json", "TEXT"),
        ("fhir_preview_json", "TEXT")
    ]:
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE queue ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass

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

    conn.commit()
    conn.close()
    _initialized_dbs.add(path)


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Creates a connection with WAL mode & row factory enabled and auto-ensures schema exists."""
    path = db_path or SQLITE_DB_PATH
    if path not in _initialized_dbs:
        init_db(path)
    conn = sqlite3.connect(path, timeout=20.0)
    _configure_connection(conn)
    return conn


def format_queue_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Helper to convert a queue row into a clean dictionary with parsed JSON fields."""
    data = dict(row)
    
    # Unpack JSON fields so FastAPI never returns double-escaped strings
    for raw_field, target_key, default_val in [
        ("marks_json", "marks", {}),
        ("pii_json", "pii", []),
        ("fhir_preview_json", "fhir", {})
    ]:
        raw_val = data.pop(raw_field, None)
        if raw_val:
            try:
                data[target_key] = json.loads(raw_val)
            except Exception:
                data[target_key] = default_val
        else:
            data[target_key] = default_val

    # Ensure frontend compatibility field aliases
    data["token"] = data.get("token_number")
    data["name"] = data.get("patient_display_name")
    data["complaint"] = data.get("chief_complaint") or ""
    return data


# ---------------------------------------------------------
# Reception & Queue DB Helpers
# ---------------------------------------------------------

def enqueue_patient(
    token_number: int,
    care_context_id: str,
    patient_display_name: str,
    abha_hash: str,
    status: str = "waiting",
    age: Optional[int] = None,
    sex: Optional[str] = None,
    chief_complaint: Optional[str] = None,
    script: Optional[str] = None,
    marks_json: Optional[str] = None,
    pii_json: Optional[str] = None,
    fhir_preview_json: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Add a patient to the daily queue."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO queue (
            token_number, care_context_id, patient_display_name, abha_hash,
            age, sex, chief_complaint, script, marks_json, pii_json, fhir_preview_json,
            status, sync_status, is_locked, cumulative_transcript
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', 0, '')
        ON CONFLICT(token_number) DO UPDATE SET
            care_context_id=excluded.care_context_id,
            patient_display_name=excluded.patient_display_name,
            abha_hash=excluded.abha_hash,
            age=excluded.age,
            sex=excluded.sex,
            chief_complaint=excluded.chief_complaint,
            script=excluded.script,
            marks_json=excluded.marks_json,
            pii_json=excluded.pii_json,
            fhir_preview_json=excluded.fhir_preview_json,
            status=excluded.status
        """,
        (
            token_number, care_context_id, patient_display_name, abha_hash,
            age, sex, chief_complaint, script, marks_json, pii_json, fhir_preview_json,
            status
        )
    )
    conn.commit()
    conn.close()
    return {
        "token_number": token_number,
        "token": token_number,
        "care_context_id": care_context_id,
        "patient_display_name": patient_display_name,
        "name": patient_display_name,
        "abha_hash": abha_hash,
        "age": age,
        "sex": sex,
        "chief_complaint": chief_complaint,
        "complaint": chief_complaint or "",
        "status": status
    }


def get_daily_queue(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all entries from today's patient queue with deserialized JSON fields."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM queue ORDER BY token_number ASC")
    rows = cursor.fetchall()
    conn.close()
    return [format_queue_row(r) for r in rows]


def get_queue_entry_by_token(token_number: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a specific queue token entry."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM queue WHERE token_number = ?", (token_number,))
    row = cursor.fetchone()
    conn.close()
    return format_queue_row(row) if row else None


def get_pending_sync_queue(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all entries from queue that are pending structuring."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM queue WHERE sync_status = 'pending_structuring' ORDER BY token_number ASC")
    rows = cursor.fetchall()
    conn.close()
    return [format_queue_row(r) for r in rows]


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


def update_sync_status(token_number: int, sync_status: str, db_path: Optional[str] = None) -> bool:
    """Update sync status for offline store-and-forward."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE queue SET sync_status = ? WHERE token_number = ?",
        (sync_status, token_number)
    )
    conn.commit()
    rows_affected = cursor.rowcount
    conn.close()
    return rows_affected > 0


def get_next_token_number(db_path: Optional[str] = None) -> int:
    """Find the next available sequential token number."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(token_number) FROM queue")
    row = cursor.fetchone()
    conn.close()
    max_token = row[0] if (row and row[0] is not None) else 0
    return max_token + 1


def create_unscheduled_patient(
    patient_name: str,
    chief_complaint: str = "Unscheduled walk-in consultation",
    clinic_id: str = "CLINIC-LOCAL",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an unscheduled walk-in patient encounter.
    Generates local anonymous care context and allocates next sequential token.
    """
    import uuid
    import hashlib
    clean_name = patient_name.strip()
    walkin_id = uuid.uuid4().hex[:8].upper()
    care_context_id = f"CC-WALKIN-{walkin_id}"
    abha_hash = hashlib.sha256(f"WALKIN-{care_context_id}".encode()).hexdigest()

    # Local care context record
    insert_care_context(
        care_context_id=care_context_id,
        raw_abha_id=f"WALKIN-{walkin_id}",
        abha_hash=abha_hash,
        clinic_id=clinic_id,
        db_path=db_path
    )

    next_token = get_next_token_number(db_path=db_path)
    return enqueue_patient(
        token_number=next_token,
        care_context_id=care_context_id,
        patient_display_name=clean_name,
        abha_hash=abha_hash,
        status="in-progress",
        chief_complaint=chief_complaint.strip() or "Unscheduled walk-in consultation",
        script=f"Patient {clean_name} presents for consultation.",
        marks_json=json.dumps({}),
        pii_json=json.dumps([]),
        fhir_preview_json=None,
        db_path=db_path
    )


# ---------------------------------------------------------
# Canonical Demo Seeding
# ---------------------------------------------------------

DEMO_PATIENTS = [
    {
        "token": 12,
        "name": "Rahul",
        "age": 34,
        "sex": "M",
        "complaint": "Fever, 3 days",
        "status": "in-progress",
        "abha": "91-4820-9182-4412",
        "context": "CC-90142",
        "script": "Patient Rahul Sharma, thirty-four years old. Presents with a severe cold, body ache, and high fever for three days. Temperature is 102. Diagnosis is a severe viral infection. Prescribed Dolo 650 three times a day, and Vitamin C. Advised complete bed rest.",
        "pii": [
            { "raw": "Rahul Sharma", "hash": "HASH_7A9B", "kind": "NAME" }
        ],
        "marks": { "symptoms": 12, "diagnosis": 24, "medication": 32, "advice": 40 },
        "fhir": {
            "symptoms": ["Severe cold", "Body ache", "High fever for three days (102°F)"],
            "diagnosis": "Severe viral infection",
            "code": "ICD-10 · B34.9",
            "medication": ["Dolo 650 · TDS", "Vitamin C"],
            "advice": ["Complete bed rest"]
        }
    },
    {
        "token": 13,
        "name": "Meena",
        "age": 52,
        "sex": "F",
        "complaint": "Follow-up, diabetes",
        "status": "waiting",
        "abha": "14-9912-3841-7782",
        "context": "CC-81203",
        "script": "Patient Meena Devi, fifty two year old female, known type two diabetes for eight years, comes for routine follow up. Reports tingling of both feet at night and increased thirst. On metformin five hundred twice daily, compliance good. Fasting sugar one hundred and sixty eight, random two twenty four, weight sixty eight kilograms. Feet examined, no ulcer, protective sensation reduced on left great toe. Impression: type two diabetes mellitus, suboptimal control with early peripheral neuropathy. Advise metformin increased to one thousand milligrams twice daily, add tablet pregabalin seventy five milligrams at night. Order HbA1c and serum creatinine. Diet counselling done, daily foot inspection advised. Residing at ward four Kolar village, contact eight eight two three one one nine zero four five. Review in one month.",
        "pii": [
            { "raw": "Meena Devi", "hash": "HASH_2F60", "kind": "NAME" },
            { "raw": "ward four Kolar village", "hash": "HASH_B812", "kind": "ADDRESS" },
            { "raw": "eight eight two three one one nine zero four five", "hash": "HASH_9D3C", "kind": "PHONE" }
        ],
        "marks": { "symptoms": 28, "diagnosis": 74, "medication": 96, "advice": 128 },
        "fhir": {
            "symptoms": ["Nocturnal paraesthesia both feet", "Polydipsia", "FBS 168 / RBS 224 mg/dL"],
            "diagnosis": "T2DM — suboptimal control, early neuropathy",
            "code": "ICD-10 · E11.42",
            "medication": ["Metformin 1000 mg · BD", "Pregabalin 75 mg · HS"],
            "advice": ["HbA1c + S. creatinine", "Daily foot inspection", "Review in 1 month"]
        }
    },
    {
        "token": 14,
        "name": "Arjun",
        "age": 7,
        "sex": "M",
        "complaint": "Cough, wheeze",
        "status": "waiting",
        "abha": "88-1204-5519-3321",
        "context": "CC-73019",
        "script": "Patient Arjun Kumar, seven year old male, brought by mother with dry cough and night time wheeze for five days, worse after playing outdoors. Two similar episodes last year. Afebrile, respiratory rate twenty six, saturation ninety seven percent on room air, bilateral expiratory wheeze present. No chest indrawing. Impression: mild episodic childhood asthma, triggered by exertion and dust. Advise salbutamol inhaler two puffs with spacer as needed, budesonide inhaler one hundred micrograms twice daily for four weeks. Mother counselled on spacer technique and trigger avoidance. Mother's mobile seven seven four five six two two one eight nine. Review after two weeks with symptom diary.",
        "pii": [
            { "raw": "Arjun Kumar", "hash": "HASH_5E18", "kind": "NAME" },
            { "raw": "seven seven four five six two two one eight nine", "hash": "HASH_A03F", "kind": "PHONE" }
        ],
        "marks": { "symptoms": 26, "diagnosis": 66, "medication": 88, "advice": 112 },
        "fhir": {
            "symptoms": ["Dry cough + nocturnal wheeze ×5 days", "Exertional trigger", "SpO₂ 97% RA, RR 26"],
            "diagnosis": "Mild episodic asthma (childhood)",
            "code": "ICD-10 · J45.20",
            "medication": ["Salbutamol MDI 2 puffs · PRN + spacer", "Budesonide 100 mcg · BD · 4 wk"],
            "advice": ["Spacer technique demo", "Dust trigger avoidance", "Review 2 wk w/ diary"]
        }
    },
    {
        "token": 15,
        "name": "Lakshmi",
        "age": 28,
        "sex": "F",
        "complaint": "ANC visit 2",
        "status": "waiting",
        "abha": "52-6619-2041-8890",
        "context": "CC-64821",
        "script": "Patient Lakshmi Bai, twenty eight year old female, second antenatal visit at twenty four weeks gestation, gravida two para one. Reports mild pedal oedema and occasional heartburn, no headache or blurring of vision. Blood pressure one hundred and twenty over seventy eight, weight fifty six kilograms, fundal height corresponds to dates, fetal heart rate one forty two per minute. Haemoglobin ten point two grams per decilitre. Impression: normal ongoing pregnancy with mild anaemia. Advise iron folic acid one tablet daily and calcium five hundred milligrams twice daily, continue for the remainder of pregnancy. Order urine routine and oral glucose tolerance test. Counselled on danger signs and institutional delivery. Aadhaar two three four five six seven eight nine zero one two. Next visit in four weeks.",
        "pii": [
            { "raw": "Lakshmi Bai", "hash": "HASH_C711", "kind": "NAME" },
            { "raw": "two three four five six seven eight nine zero one two", "hash": "HASH_44D8", "kind": "AADHAAR" }
        ],
        "marks": { "symptoms": 30, "diagnosis": 78, "medication": 96, "advice": 124 },
        "fhir": {
            "symptoms": ["Mild pedal oedema", "Heartburn", "Hb 10.2 g/dL · FHR 142 bpm"],
            "diagnosis": "Normal pregnancy @24 wk with mild anaemia",
            "code": "ICD-10 · O99.011",
            "medication": ["IFA 1 tab · OD", "Calcium 500 mg · BD"],
            "advice": ["Urine routine + OGTT", "Danger-sign counselling", "Next ANC in 4 wk"]
        }
    },
    {
        "token": 16,
        "name": "Ibrahim",
        "age": 61,
        "sex": "M",
        "complaint": "Chest tightness",
        "status": "waiting",
        "abha": "63-8812-4019-1122",
        "context": "CC-55910",
        "script": "Patient Ibrahim Sheikh, sixty one year old male, complains of chest tightness on walking uphill for two weeks, relieved by rest within five minutes. Known hypertensive on amlodipine five milligrams, smoker twenty pack years. No pain at rest, no syncope. Blood pressure one forty six over eighty eight, pulse seventy eight regular, chest clear, no murmurs. Electrocardiogram shows T wave flattening in lateral leads. Impression: stable exertional angina, high cardiovascular risk. Advise aspirin seventy five milligrams daily, atorvastatin twenty milligrams at night, continue amlodipine, sorbitrate sublingual for chest pain. Refer to district hospital cardiology within one week for stress testing. Smoking cessation counselling given. Contact nine four four one two seven six five three zero. Return immediately if pain at rest.",
        "pii": [
            { "raw": "Ibrahim Sheikh", "hash": "HASH_D2A5", "kind": "NAME" },
            { "raw": "nine four four one two seven six five three zero", "hash": "HASH_61BE", "kind": "PHONE" }
        ],
        "marks": { "symptoms": 26, "diagnosis": 80, "medication": 104, "advice": 132 },
        "fhir": {
            "symptoms": ["Exertional chest tightness ×2 wk", "Relieved by rest <5 min", "ECG: lateral T flattening"],
            "diagnosis": "Stable exertional angina — high CV risk",
            "code": "ICD-10 · I20.8",
            "medication": ["Aspirin 75 mg · OD", "Atorvastatin 20 mg · HS", "Sorbitrate 5 mg · SL PRN"],
            "advice": ["Cardiology referral ≤1 wk", "Smoking cessation", "Return if rest pain"]
        }
    },
    {
        "token": 17,
        "name": "Sunita",
        "age": 45,
        "sex": "F",
        "complaint": "Joint pain",
        "status": "waiting",
        "abha": "77-3319-8204-5512",
        "context": "CC-48192",
        "script": "Patient Sunita Rani, forty five year old female, reports pain and morning stiffness of both wrists and finger joints for three months, stiffness lasting nearly an hour. Difficulty gripping utensils. No rash, no oral ulcers. Tenderness with mild swelling of metacarpophalangeal joints bilaterally, no deformity. Impression: inflammatory polyarthritis, rheumatoid arthritis suspected. Advise naproxen two fifty milligrams twice daily after food for seven days. Order rheumatoid factor, anti CCP, and erythrocyte sedimentation rate. Refer to medicine outpatient for disease modifying therapy. Review with reports in ten days.",
        "pii": [
            { "raw": "Sunita Rani", "hash": "HASH_8B3D", "kind": "NAME" }
        ],
        "marks": { "symptoms": 30, "diagnosis": 66, "medication": 80, "advice": 104 },
        "fhir": {
            "symptoms": ["Symmetric wrist + MCP pain ×3 mo", "Morning stiffness ~60 min", "Grip weakness"],
            "diagnosis": "Inflammatory polyarthritis — ? rheumatoid",
            "code": "ICD-10 · M06.9",
            "medication": ["Naproxen 250 mg · BD · PC · 7 days"],
            "advice": ["RF + anti-CCP + ESR", "Medicine OPD referral", "Review in 10 days"]
        }
    }
]


def seed_demo_queue(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Idempotently seeds canonical mock patients into local SQLite database."""
    import hashlib
    import hmac

    salt = os.getenv("ABDM_SALT", "medsync-sih-2026-edge-node-salt-secret").encode()

    def make_hash(abha_id: str) -> str:
        return hmac.new(salt, abha_id.encode(), hashlib.sha256).hexdigest()

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # 1. Atomic Idempotent Cleanup: Clear prior demo token entries (including legacy tokens 1..4)
    cursor.execute("DELETE FROM queue WHERE token_number IN (1, 2, 3, 4, 12, 13, 14, 15, 16, 17)")
    cursor.execute("DELETE FROM care_contexts WHERE care_context_id IN ('CC-90142', 'CC-81203', 'CC-73019', 'CC-64821', 'CC-55910', 'CC-48192')")
    conn.commit()

    # 2. Insert canonical records
    for p in DEMO_PATIENTS:
        h = make_hash(p["abha"])
        insert_care_context(p["context"], p["abha"], h, "CLINIC-01", db_path)
        enqueue_patient(
            token_number=p["token"],
            care_context_id=p["context"],
            patient_display_name=p["name"],
            abha_hash=h,
            status=p["status"],
            age=p["age"],
            sex=p["sex"],
            chief_complaint=p["complaint"],
            script=p["script"],
            marks_json=json.dumps(p["marks"]),
            pii_json=json.dumps(p["pii"]),
            fhir_preview_json=json.dumps(p["fhir"]),
            db_path=db_path
        )

    return get_daily_queue(db_path)


def ensure_seeded_db(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Checks if canonical demo patients exist in the SQLite database; if missing or legacy, cleans and seeds."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM queue WHERE token_number IN (12, 13, 14, 15, 16)")
    row = cursor.fetchone()
    count = row["cnt"] if row else 0

    cursor.execute("SELECT COUNT(*) as legacy_cnt FROM queue WHERE token_number IN (1, 2, 3, 4)")
    legacy_row = cursor.fetchone()
    legacy_count = legacy_row["legacy_cnt"] if legacy_row else 0
    conn.close()

    if count < 5 or legacy_count > 0:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM queue WHERE token_number IN (1, 2, 3, 4)")
        conn.commit()
        conn.close()
        return seed_demo_queue(db_path)
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

def get_encounter_by_care_context(care_context_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch an encrypted encounter by its care_context_id."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT bundle_id, care_context_id, payload, nonce, tag, record_hash, prev_hash, created_at FROM encounters WHERE care_context_id = ?",
        (care_context_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

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

