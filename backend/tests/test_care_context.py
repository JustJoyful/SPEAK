import os
import pytest
from backend.pipeline.care_context import (
    generate_abha_hash,
    generate_care_context_id,
    create_and_store_care_context,
    resolve_care_context
)
from backend.db.local import init_db

@pytest.fixture
def test_db_path(tmp_path):
    db_path = str(tmp_path / "test_care_context.db")
    init_db(db_path)
    return db_path

def test_generate_abha_hash():
    abha_id = "91-1234-5678-9012"
    hash1 = generate_abha_hash(abha_id, salt="test-salt")
    hash2 = generate_abha_hash(abha_id, salt="test-salt")
    hash3 = generate_abha_hash(abha_id, salt="different-salt")
    
    assert hash1 == hash2
    assert hash1 != hash3

def test_generate_care_context_id():
    cc_id = generate_care_context_id()
    assert cc_id.startswith("CC-")
    assert len(cc_id) == 9
    assert cc_id[3:].isdigit()

def test_bidirectional_mapping_integrity(test_db_path):
    raw_abha_id = "91-9999-8888-7777"
    clinic_id = "CLINIC-TEST-01"
    
    # Store
    stored = create_and_store_care_context(raw_abha_id, clinic_id, db_path=test_db_path)
    cc_id = stored["care_context_id"]
    
    assert cc_id.startswith("CC-")
    assert stored["raw_abha_id"] == raw_abha_id
    assert stored["clinic_id"] == clinic_id
    
    # Resolve
    resolved = resolve_care_context(cc_id, db_path=test_db_path)
    
    assert resolved is not None
    assert resolved["care_context_id"] == cc_id
    assert resolved["raw_abha_id"] == raw_abha_id
    assert resolved["abha_hash"] == stored["abha_hash"]
    assert resolved["clinic_id"] == clinic_id

def test_resolve_invalid_context(test_db_path):
    resolved = resolve_care_context("CC-000000", db_path=test_db_path)
    assert resolved is None
