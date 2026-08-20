"""Unit tests for MedSync Pydantic schemas and NRCeS FHIR R4 models."""

import pytest
from datetime import datetime
from backend.pipeline.fhir_schema import (
    QueueEntry,
    ChecklistState,
    CareContext,
    FHIROPConsultRecord,
    FHIRPatientReference,
    FHIRCondition,
    FHIRCodeableConcept,
    FHIRCoding,
    FHIRMedicationStatement,
    FHIRMedicationDosage,
    FHIRVitalSign,
    EncryptedBundle,
    SyncPointer
)


def test_queue_entry_model():
    entry = QueueEntry(
        token_number=1,
        care_context_id="CC-90142",
        patient_display_name="Priya Sharma",
        abha_hash="abcdef1234567890",
        status="waiting"
    )
    assert entry.token_number == 1
    assert entry.status == "waiting"
    assert entry.patient_display_name == "Priya Sharma"


def test_checklist_state_model():
    state = ChecklistState(
        symptoms_present=True,
        diagnosis_present=True,
        medication_present=False,
        advice_present=False
    )
    assert state.symptoms_present is True
    assert state.medication_present is False


def test_fhir_op_consult_record_validation():
    record = FHIROPConsultRecord(
        subject=FHIRPatientReference(reference="CareContext/CC-90142", display="Anonymous Patient"),
        chief_complaints=["Persistent headache for 3 days", "Elevated blood pressure"],
        vitals=[
            FHIRVitalSign(vital_name="Blood Pressure", value="140/90 mmHg", interpretation="Elevated")
        ],
        diagnoses=[
            FHIRCondition(
                code=FHIRCodeableConcept(
                    coding=[FHIRCoding(system="http://snomed.info/sct", code="38341003", display="Hypertensive disorder")],
                    text="Essential Hypertension"
                )
            )
        ],
        medications=[
            FHIRMedicationStatement(
                medication=FHIRCodeableConcept(text="Tab Telmisartan 40mg"),
                dosage=FHIRMedicationDosage(timing="1-0-0 (OD)", duration="1 month", route="oral")
            )
        ],
        advice_and_followup="Low sodium diet, review in 4 weeks."
    )
    assert record.resource_type == "Bundle"
    assert record.subject.reference == "CareContext/CC-90142"
    assert len(record.diagnoses) == 1
    assert len(record.medications) == 1


def test_encrypted_bundle_and_sync_pointer():
    bundle = EncryptedBundle(
        bundle_id="uuid-1234",
        care_context_id="CC-90142",
        payload="base64ciphertext",
        nonce="base64nonce",
        tag="base64tag",
        record_hash="a"*64,
        prev_hash="0"*64
    )
    assert bundle.bundle_id == "uuid-1234"

    pointer = SyncPointer(
        sync_id="sync-1234",
        abha_hash="b"*64,
        clinic_id="CLINIC-01",
        record_hash="a"*64
    )
    assert pointer.clinic_id == "CLINIC-01"
