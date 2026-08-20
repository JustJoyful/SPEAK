"""Pydantic schemas and NRCeS FHIR R4 data models for MedSync."""

from datetime import datetime, timezone
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------
# 1. Reception & Queue Models (Decoupled Identity Flow)
# ---------------------------------------------------------

class QueueEntry(BaseModel):
    """Patient entry in the daily clinic queue.
    
    The doctor screen sees token_number, patient_display_name, and status.
    Raw ABHA ID is never stored in this model.
    """
    token_number: int = Field(..., description="Daily incremental token number (e.g., 1, 2, 3)")
    care_context_id: str = Field(..., description="Assigned local Care-Context ID (e.g. CC-98124)")
    patient_display_name: str = Field(..., description="Human friendly name for queue calling (e.g. Priya Sharma)")
    abha_hash: str = Field(..., description="HMAC-SHA256 salted hash of patient ABHA ID")
    status: Literal["waiting", "in-progress", "done"] = Field(
        default="waiting",
        description="Current queue status of the patient encounter"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when patient was enqueued"
    )


class ChecklistState(BaseModel):
    """Dynamic passive checklist state extracted from partial dictation on pause.
    
    Acts as an advisory guide for the physician before finalization.
    """
    symptoms_present: bool = Field(default=False, description="Whether chief complaints/symptoms are detected")
    diagnosis_present: bool = Field(default=False, description="Whether a provisional/confirmed diagnosis is detected")
    medication_present: bool = Field(default=False, description="Whether prescribed drug/dosage is detected")
    advice_present: bool = Field(default=False, description="Whether follow-up instructions/advice are detected")


# ---------------------------------------------------------
# 2. Local Care-Context Models (Edge Only, Zero-Trust)
# ---------------------------------------------------------

class CareContext(BaseModel):
    """Local Care-Context linking hash to local clinic encounter context.
    
    This model NEVER leaves the local edge node/database.
    """
    care_context_id: str = Field(
        ...,
        description="Unique local Care-Context reference ID (e.g., CC-XXXXXXXX)"
    )
    raw_abha_id: Optional[str] = Field(
        default=None,
        description="Real ABHA ID stored exclusively on local edge SQLite for doctor re-association"
    )
    abha_hash: str = Field(
        ...,
        description="HMAC-SHA256 salted hash of patient ABHA ID"
    )
    clinic_id: str = Field(
        ...,
        description="Identifier of local clinic/hospital"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of context creation"
    )


# ---------------------------------------------------------
# 3. NRCeS FHIR R4 Models (Minimal Compliant OP-Consult Subset)
# ---------------------------------------------------------

class FHIRCoding(BaseModel):
    system: str = Field(default="http://snomed.info/sct", description="Coding system (SNOMED-CT / ICD-10 / LOINC)")
    code: Optional[str] = Field(default=None, description="Standard code if identified")
    display: str = Field(..., description="Human-readable term")


class FHIRCodeableConcept(BaseModel):
    coding: List[FHIRCoding] = Field(default_factory=list)
    text: str = Field(..., description="Original extracted clinical text")


class FHIRPatientReference(BaseModel):
    reference: str = Field(
        ...,
        description="Must be CareContext/CC-XXXX (ABHA ID is strictly forbidden here)"
    )
    display: str = Field(default="Anonymous Patient Context")


class FHIRPractitioner(BaseModel):
    name: str = Field(default="Attending Physician")
    qualification: Optional[str] = Field(default="MBBS, MD")
    registration_number: Optional[str] = Field(default="MCI-XXXXXXXX")


class FHIRVitalSign(BaseModel):
    vital_name: str = Field(..., description="E.g., Blood Pressure, Heart Rate, SpO2, Temperature")
    value: str = Field(..., description="E.g., 120/80 mmHg, 72 bpm, 98%")
    interpretation: Optional[str] = Field(default=None, description="Normal / Elevated / Critical")


class FHIRCondition(BaseModel):
    clinical_status: str = Field(default="active", description="active | recurrence | relapse | remission | resolved")
    verification_status: str = Field(default="confirmed", description="unconfirmed | provisional | differential | confirmed")
    code: FHIRCodeableConcept = Field(..., description="Diagnosis or symptom concept")
    notes: Optional[str] = Field(default=None, description="Clinical notes / observation")


class FHIRMedicationDosage(BaseModel):
    timing: str = Field(..., description="E.g., 1-0-1 (after food), TID, OD, SOS")
    duration: str = Field(..., description="E.g., 5 days, 1 month")
    route: str = Field(default="oral", description="oral | topical | intravenous | etc.")
    instructions: Optional[str] = Field(default=None, description="Additional intake instructions")


class FHIRMedicationStatement(BaseModel):
    medication: FHIRCodeableConcept = Field(..., description="Drug brand name or generic compound")
    dosage: FHIRMedicationDosage = Field(..., description="Dosage and frequency details")
    reason: Optional[str] = Field(default=None, description="Indication for drug")


class FHIROPConsultRecord(BaseModel):
    """NRCeS-aligned Outpatient (OP) Consultation Record FHIR R4 Bundle subset."""
    resource_type: str = Field(default="Bundle", description="FHIR Resource Type")
    bundle_type: str = Field(default="document", description="NRCeS Document Bundle")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Header Information
    subject: FHIRPatientReference = Field(
        ...,
        description="Patient reference containing local CareContext ID only"
    )
    practitioner: FHIRPractitioner = Field(default_factory=FHIRPractitioner)
    
    # Clinical Sections
    chief_complaints: List[str] = Field(
        default_factory=list,
        description="Primary reasons for visit"
    )
    vitals: List[FHIRVitalSign] = Field(
        default_factory=list,
        description="Vital signs recorded during consultation"
    )
    diagnoses: List[FHIRCondition] = Field(
        default_factory=list,
        description="Diagnosed conditions or clinical impressions"
    )
    medications: List[FHIRMedicationStatement] = Field(
        default_factory=list,
        description="Prescribed medications and dosages"
    )
    advice_and_followup: Optional[str] = Field(
        default=None,
        description="Dietary advice, investigations requested, and follow-up timeline"
    )


# ---------------------------------------------------------
# 4. Cryptographic Storage & Central Indexing Models
# ---------------------------------------------------------

class EncryptedBundle(BaseModel):
    """Locally stored encrypted FHIR document bundle with cryptographic tamper-evident seal."""
    bundle_id: str = Field(..., description="Unique record UUID")
    care_context_id: str = Field(..., description="Associated Care-Context ID")
    payload: str = Field(..., description="Base64-encoded AES-256-GCM ciphertext")
    nonce: str = Field(..., description="Base64-encoded 96-bit AES-GCM nonce")
    tag: str = Field(..., description="Base64-encoded 128-bit authentication tag")
    record_hash: str = Field(..., description="SHA-256 hash of this record's plaintext content")
    prev_hash: str = Field(..., description="SHA-256 hash of previous block in the edge hash chain")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SyncPointer(BaseModel):
    """Zero-Knowledge sync pointer transmitted to the central Turso index.
    
    Contains NO clinical data and NO identifiable patient information.
    """
    sync_id: str = Field(..., description="Unique pointer UUID")
    abha_hash: str = Field(..., description="HMAC-SHA256 salted hash of ABHA ID")
    clinic_id: str = Field(..., description="Local clinic identifier")
    record_hash: str = Field(..., description="Tamper-evident verification hash of encrypted record")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
