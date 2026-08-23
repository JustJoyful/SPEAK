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
    assert len(queue) == 6
    assert queue[0]["token_number"] == 12
    assert queue[0]["token"] == 12
    assert queue[0]["patient_display_name"] == "Rahul"
    assert queue[0]["name"] == "Rahul"
    assert queue[0]["complaint"] == "Fever, 3 days"
    assert isinstance(queue[0]["marks"], dict)
    assert isinstance(queue[0]["fhir"], dict)

    # Enqueue an extra patient
    enqueue_patient(
        token_number=18,
        care_context_id="CC-55555",
        patient_display_name="Karan Malhotra",
        abha_hash="hash555",
        status="waiting",
        db_path=TEST_DB
    )
    updated_queue = get_daily_queue(TEST_DB)
    assert len(updated_queue) == 7
    assert updated_queue[6]["patient_display_name"] == "Karan Malhotra"


def test_active_encounter_session_lifecycle():
    seed_demo_queue(TEST_DB)
    session = ActiveEncounterSession()

    # 1. Select token #12
    res = session.select_token(12, db_path=TEST_DB)
    assert res["status"] == "success"
    assert res["token_number"] == 12
    assert res["patient_display_name"] == "Rahul"

    # Verify DB status changed to in-progress
    entry = get_queue_entry_by_token(12, db_path=TEST_DB)
    assert entry["status"] == "in-progress"

    # 2. Append dictation
    session.append_transcript(12, "Patient has mild fever.", db_path=TEST_DB)
    state1 = session.get_current_state(12, db_path=TEST_DB)
    assert state1["is_locked"] is True
    
    entry = get_queue_entry_by_token(12, db_path=TEST_DB)
    assert "mild fever" in entry["cumulative_transcript"]

    # 3. Attempting to switch tokens while locked must raise 409
    with pytest.raises(HTTPException) as exc_info:
        session.select_token(12, db_path=TEST_DB)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == "SESSION_LOCKED"

    # 4. Clear session and switch
    session.clear_session(12, db_path=TEST_DB)
    state_cleared = session.get_current_state(12, db_path=TEST_DB)
    assert state_cleared["is_locked"] is False
    assert state_cleared["has_transcript"] is False

    res2 = session.select_token(13, db_path=TEST_DB)
    assert res2["token_number"] == 13

