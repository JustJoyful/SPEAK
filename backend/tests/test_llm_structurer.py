import pytest
from backend.pipeline.llm_structurer import inject_care_context
from backend.pipeline.fhir_schema import FHIROPConsultRecord
from pydantic import ValidationError

# 10 Sample Structured Clinical Notes (simulating LLM output)
SAMPLE_NOTES = [
    {
        # Note 1: Simple Fever
        "chief_complaints": ["High fever for 2 days"],
        "diagnoses": [{"code": {"text": "Viral Fever", "coding": [{"display": "Viral Fever", "system": "http://snomed.info/sct"}]}}],
        "medications": [{"medication": {"text": "Paracetamol 500mg", "coding": [{"display": "Paracetamol", "system": "http://snomed.info/sct"}]}, "dosage": {"timing": "1-1-1", "duration": "3 days", "route": "oral"}}],
    },
    {
        # Note 2: Hypertension
        "chief_complaints": ["Headache", "Dizziness"],
        "vitals": [{"vital_name": "Blood Pressure", "value": "150/95 mmHg", "interpretation": "Elevated"}],
        "diagnoses": [{"code": {"text": "Essential Hypertension", "coding": [{"display": "Essential Hypertension", "system": "http://snomed.info/sct"}]}}],
        "medications": [{"medication": {"text": "Amlodipine 5mg", "coding": [{"display": "Amlodipine", "system": "http://snomed.info/sct"}]}, "dosage": {"timing": "1-0-0", "duration": "30 days", "route": "oral"}}],
        "advice_and_followup": "Review after 1 month, low salt diet."
    },
    {
        # Note 3: Diabetes
        "chief_complaints": ["Increased thirst", "Frequent urination"],
        "vitals": [{"vital_name": "Fasting Blood Sugar", "value": "180 mg/dL"}],
        "diagnoses": [{"code": {"text": "Type 2 Diabetes Mellitus", "coding": [{"display": "T2DM", "system": "http://snomed.info/sct"}]}}],
        "medications": [{"medication": {"text": "Metformin 500mg", "coding": [{"display": "Metformin", "system": "http://snomed.info/sct"}]}, "dosage": {"timing": "1-0-1", "duration": "15 days", "route": "oral"}}],
    },
    {
        # Note 4: Asthma
        "chief_complaints": ["Shortness of breath", "Wheezing"],
        "vitals": [{"vital_name": "SpO2", "value": "94%", "interpretation": "Low"}],
        "diagnoses": [{"code": {"text": "Bronchial Asthma", "coding": [{"display": "Asthma", "system": "http://snomed.info/sct"}]}}],
        "medications": [{"medication": {"text": "Salbutamol Inhaler", "coding": [{"display": "Salbutamol", "system": "http://snomed.info/sct"}]}, "dosage": {"timing": "SOS", "duration": "As needed", "route": "inhalation"}}],
    },
    {
        # Note 5: Common Cold
        "chief_complaints": ["Runny nose", "Cough"],
        "diagnoses": [{"code": {"text": "Upper Respiratory Tract Infection", "coding": [{"display": "URTI", "system": "http://snomed.info/sct"}]}}],
        "medications": [],
        "advice_and_followup": "Warm fluids, rest for 2 days."
    },
    {
        # Note 6: Back Pain
        "chief_complaints": ["Lower back pain for 1 week"],
        "diagnoses": [{"code": {"text": "Lumbago", "coding": [{"display": "Lumbago", "system": "http://snomed.info/sct"}]}}],
        "medications": [{"medication": {"text": "Ibuprofen 400mg", "coding": [{"display": "Ibuprofen", "system": "http://snomed.info/sct"}]}, "dosage": {"timing": "1-0-1", "duration": "5 days", "route": "oral"}}],
    },
    {
        # Note 7: Gastroenteritis
        "chief_complaints": ["Vomiting", "Loose stools"],
        "diagnoses": [{"code": {"text": "Acute Gastroenteritis", "coding": [{"display": "Gastroenteritis", "system": "http://snomed.info/sct"}]}}],
        "medications": [{"medication": {"text": "ORS", "coding": [{"display": "ORS", "system": "http://snomed.info/sct"}]}, "dosage": {"timing": "Frequent", "duration": "3 days", "route": "oral"}}],
    },
    {
        # Note 8: Migraine
        "chief_complaints": ["Severe unilateral headache", "Nausea"],
        "diagnoses": [{"code": {"text": "Migraine", "coding": [{"display": "Migraine", "system": "http://snomed.info/sct"}]}}],
        "medications": [{"medication": {"text": "Sumatriptan 50mg", "coding": [{"display": "Sumatriptan", "system": "http://snomed.info/sct"}]}, "dosage": {"timing": "SOS", "duration": "Max 2 per day", "route": "oral"}}],
    },
    {
        # Note 9: Conjunctivitis
        "chief_complaints": ["Redness in both eyes", "Watering"],
        "diagnoses": [{"code": {"text": "Acute Conjunctivitis", "coding": [{"display": "Conjunctivitis", "system": "http://snomed.info/sct"}]}}],
        "medications": [{"medication": {"text": "Moxifloxacin Eye Drops", "coding": [{"display": "Moxifloxacin", "system": "http://snomed.info/sct"}]}, "dosage": {"timing": "1 drop QID", "duration": "5 days", "route": "topical"}}],
    },
    {
        # Note 10: General Checkup
        "chief_complaints": ["Routine health check"],
        "vitals": [
            {"vital_name": "Blood Pressure", "value": "120/80 mmHg", "interpretation": "Normal"},
            {"vital_name": "Heart Rate", "value": "72 bpm", "interpretation": "Normal"}
        ],
        "diagnoses": [],
        "medications": [],
        "advice_and_followup": "All parameters normal. Maintain healthy lifestyle."
    }
]

def test_pydantic_schema_validation_gate():
    care_context_id = "CC-123456"
    
    for note in SAMPLE_NOTES:
        # Auto-inject the care context ID to simulate backend middleware
        injected_json = inject_care_context(note.copy(), care_context_id)
        
        # Pydantic schema validation gate
        record = FHIROPConsultRecord.model_validate(injected_json)
        
        # Assertions
        assert record.resource_type == "Bundle"
        assert record.subject.reference == f"CareContext/{care_context_id}"
        
def test_pydantic_schema_validation_failure():
    # Test that a malformed JSON fails validation
    care_context_id = "CC-123456"
    malformed_note = {
        "chief_complaints": "Should be a list but is a string",
        "diagnoses": [{"code": "Missing nested fields"}]
    }
    injected_json = inject_care_context(malformed_note, care_context_id)
    
    with pytest.raises(ValidationError):
        FHIROPConsultRecord.model_validate(injected_json)
