"""Tests for SQLite Lifespan Startup Seeding, WAL Concurrency, and JSON Deserialization."""

import os
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.db.local import (
    init_db,
    seed_demo_queue,
    ensure_seeded_db,
    get_daily_queue,
    get_queue_entry_by_token,
    get_db_connection
)

TEST_DB = "test_startup_seeding.db"
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_teardown():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    init_db(TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    for ext in ["-wal", "-shm"]:
        if os.path.exists(TEST_DB + ext):
            os.remove(TEST_DB + ext)


def test_seed_idempotency():
    """Verify that seeding multiple times does not throw unique constraint errors."""
    q1 = seed_demo_queue(TEST_DB)
    assert len(q1) == 6
    tokens1 = [p["token_number"] for p in q1]
    assert tokens1 == [12, 13, 14, 15, 16, 17]

    # Re-seed immediately
    q2 = seed_demo_queue(TEST_DB)
    assert len(q2) == 6
    tokens2 = [p["token_number"] for p in q2]
    assert tokens2 == [12, 13, 14, 15, 16, 17]


def test_ensure_seeded_db():
    """Verify ensure_seeded_db seeds when empty and is a no-op when already seeded."""
    # First call seeds
    q = ensure_seeded_db(TEST_DB)
    assert len(q) == 6

    # Second call detects presence and returns queue directly
    q2 = ensure_seeded_db(TEST_DB)
    assert len(q2) == 6


def test_json_deserialization_no_double_escaping():
    """Verify that marks, pii, and fhir are returned as Python dicts/lists, not raw strings."""
    seed_demo_queue(TEST_DB)
    entry = get_queue_entry_by_token(12, TEST_DB)
    assert entry is not None
    assert isinstance(entry["marks"], dict)
    assert entry["marks"]["symptoms"] == 22
    assert isinstance(entry["pii"], list)
    assert len(entry["pii"]) == 2
    assert isinstance(entry["fhir"], dict)
    assert "symptoms" in entry["fhir"]
    assert "ICD-10" in entry["fhir"]["code"]


def test_wal_mode_enabled():
    """Verify that SQLite connection is running in WAL mode."""
    conn = get_db_connection(TEST_DB)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode;")
    mode = cursor.fetchone()[0]
    conn.close()
    assert mode.lower() == "wal"


def test_get_today_queue_endpoint():
    """Verify /queue/today returns parsed objects with status 200."""
    response = client.get("/queue/today", headers={"X-Role": "Receptionist"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 5
    first = data[0]
    assert first["token"] == 12
    assert isinstance(first["marks"], dict)
    assert isinstance(first["fhir"], dict)
