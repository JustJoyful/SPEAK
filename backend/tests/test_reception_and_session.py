"""Unit tests for Phase 1.5: Reception Queue and Active Encounter Session."""

import os
import pytest
from fastapi import HTTPException
from backend.db.local import (
    init_db,
    seed_demo_queue,
    get_daily_queue,
    get_queue_entry_by_token,
    update_token_status,
    enqueue_patient
)
from backend.session.active_encounter import ActiveEncounterSession

TEST_DB = "test_medsync_phase15.db"


@pytest.fixture(autouse=True)
def setup_teardown_db():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    init_db(TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


def test_queue_seeding_and_retrieval():
    queue = seed_demo_queue(TEST_DB)
    assert len(queue) == 4
    assert queue[0]["token_number"] == 1
    assert queue[0]["patient_display_name"] == "Priya Sharma"
    assert queue[0]["status"] == "waiting"

    # Enqueue a 5th patient
    enqueue_patient(
        token_number=5,
        care_context_id="CC-55555",
        patient_display_name="Karan Malhotra",
        abha_hash="hash555",
        status="waiting",
        db_path=TEST_DB
    )
    updated_queue = get_daily_queue(TEST_DB)
    assert len(updated_queue) == 5
    assert updated_queue[4]["patient_display_name"] == "Karan Malhotra"


def test_active_encounter_session_lifecycle():
    seed_demo_queue(TEST_DB)
    session = ActiveEncounterSession()

    # 1. Select token #1
    res = session.select_token(1, db_path=TEST_DB)
    assert res["status"] == "success"
    assert res["token_number"] == 1
    assert res["patient_display_name"] == "Priya Sharma"

    # Verify DB status changed to in-progress
    entry = get_queue_entry_by_token(1, db_path=TEST_DB)
    assert entry["status"] == "in-progress"

    # 2. Append dictation
    session.append_transcript(1, "Patient has mild fever.", db_path=TEST_DB)
    state1 = session.get_current_state(1, db_path=TEST_DB)
    assert state1["is_locked"] is True
    
    entry = get_queue_entry_by_token(1, db_path=TEST_DB)
    assert "mild fever" in entry["cumulative_transcript"]

    # 3. Attempting to switch tokens while locked must raise 409
    with pytest.raises(HTTPException) as exc_info:
        session.select_token(1, db_path=TEST_DB)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == "SESSION_LOCKED"

    # 4. Clear session and switch
    session.clear_session(1, db_path=TEST_DB)
    state_cleared = session.get_current_state(1, db_path=TEST_DB)
    assert state_cleared["is_locked"] is False
    assert state_cleared["has_transcript"] is False

    res2 = session.select_token(2, db_path=TEST_DB)
    assert res2["token_number"] == 2

