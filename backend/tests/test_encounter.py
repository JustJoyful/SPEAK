import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from backend.main import app
from backend.db.local import init_db, get_daily_queue, enqueue_patient, insert_care_context

TEST_DB = "test_medsync.db"
client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_teardown():
    """Setup and teardown the test database for each test."""
    init_db(TEST_DB)
    # Seed a patient for testing
    import hashlib, hmac, os
    salt = os.getenv("ABDM_SALT", "medsync-sih-2026-edge-node-salt-secret").encode()
    abha_hash = hmac.new(salt, "91-4820-9182-4412".encode(), hashlib.sha256).hexdigest()
    insert_care_context("CC-TEST-123", "91-4820-9182-4412", abha_hash, "CLINIC-123", db_path=TEST_DB)
    enqueue_patient(1, "CC-TEST-123", "Priya Sharma", abha_hash, db_path=TEST_DB)
    
    yield
    # Teardown logic
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
        
def get_token():
    q = get_daily_queue(TEST_DB)
    return q[0]["token_number"]

def test_select_patient_requires_doctor_role():
    token = get_token()
    response = client.post(f"/encounter/{token}/select", headers={"X-Role": "Receptionist"})
    assert response.status_code == 403

def test_select_patient_success():
    token = get_token()
    # Need to patch the active_session so it uses TEST_DB
    with patch("backend.routes.encounter.active_session.select_token") as mock_select:
        mock_select.return_value = {"status": "success", "token_number": token}
        
        response = client.post(f"/encounter/{token}/select", headers={"X-Role": "Doctor"})
        assert response.status_code == 200
        assert response.json()["status"] == "success"

def test_reset_encounter():
    token = get_token()
    with patch("backend.routes.encounter.active_session.clear_session") as mock_clear:
        response = client.post(f"/encounter/{token}/reset", headers={"X-Role": "Doctor"})
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_clear.assert_called_once_with(token)


@patch("backend.routes.encounter.active_session.append_transcript")
@patch("backend.routes.encounter.extract_checklist")
@patch("backend.routes.encounter.event_bus.publish")
def test_append_transcript(mock_publish, mock_extract, mock_append):
    token = get_token()
    mock_append.return_value = "patient complains of mild fever"
    
    # Mock extract_checklist to return a checklist
    mock_checklist = MagicMock()
    mock_checklist.model_dump.return_value = {"symptoms_present": True}
    mock_extract.return_value = (mock_checklist, "")
    
    response = client.post(
        f"/encounter/{token}/transcript", 
        json={"text": "patient complains of mild fever"},
        headers={"X-Role": "Doctor"}
    )
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_publish.assert_any_call(f"checklist_{token}", {"symptoms_present": True})

@patch("backend.routes.encounter.active_session.get_current_state")
@patch("backend.routes.encounter.get_queue_entry_by_token")
@patch("backend.routes.encounter.update_token_status")
@patch("backend.routes.encounter.active_session.clear_session")
@patch("backend.db.local.update_sync_status")
@patch("backend.db.local.update_session_transcript")
def test_finalize_encounter(mock_update_transcript, mock_update_sync, mock_clear, mock_update, mock_get_entry, mock_get_state):
    token = get_token()
    
    # Mocking state
    mock_get_state.return_value = {"has_transcript": True}
    mock_get_entry.return_value = {
        "cumulative_transcript": "fever",
        "care_context_id": "CC-123",
        "abha_hash": "hash123"
    }
    
    response = client.post(f"/encounter/{token}/finalize", headers={"X-Role": "Doctor"})
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["sync_status"] == "pending_structuring"
    mock_update.assert_called_once_with(token, "done")
    mock_update_sync.assert_called_once_with(token, "pending_structuring")


@patch("backend.routes.encounter.active_session.get_current_state")
@patch("backend.routes.encounter.get_queue_entry_by_token")
@patch("backend.routes.encounter.update_token_status")
@patch("backend.routes.encounter.active_session.clear_session")
@patch("backend.db.local.update_sync_status")
@patch("backend.db.local.update_session_transcript")
def test_finalize_encounter_with_typed_text(mock_update_transcript, mock_update_sync, mock_clear, mock_update, mock_get_entry, mock_get_state):
    token = get_token()
    
    mock_get_state.return_value = {"has_transcript": True}
    mock_get_entry.return_value = {
        "cumulative_transcript": "Patient typed clinical history directly.",
        "care_context_id": "CC-123",
        "abha_hash": "hash123"
    }
    
    response = client.post(
        f"/encounter/{token}/finalize",
        json={"text": "Patient typed clinical history directly.", "language": "en-IN"},
        headers={"X-Role": "Doctor"}
    )
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_update_transcript.assert_any_call(token, "Patient typed clinical history directly.", is_locked=False)

