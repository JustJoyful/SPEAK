"""Unit tests for Phase 2: Presidio Local Edge PII Masking Engine."""

import re
import pytest
from backend.pipeline.pii_mask import mask_pii, PIIMasker


@pytest.fixture(scope="module")
def masker():
    return PIIMasker()


def test_abha_id_redaction(masker):
    text1 = "Patient ABHA is 91-4820-9182-4412 for registration."
    res1 = masker.mask(text1)
    assert "<ABHA_ID>" in res1["sanitized_text"]
    assert "91-4820-9182-4412" not in res1["sanitized_text"]

    text2 = "Patient handle: priya.sharma@abdm"
    res2 = masker.mask(text2)
    assert "<ABHA_ID>" in res2["sanitized_text"]
    assert "priya.sharma@abdm" not in res2["sanitized_text"]


def test_aadhaar_redaction(masker):
    text = "UIDAI Aadhaar number 4920 1823 9912 verified at clinic."
    res = masker.mask(text)
    assert "<AADHAAR_NUMBER>" in res["sanitized_text"]
    assert "4920 1823 9912" not in res["sanitized_text"]


def test_phone_redaction(masker):
    text = "Emergency contact +91 9876543210 or 9845012345."
    res = masker.mask(text)
    assert "<PHONE_NUMBER>" in res["sanitized_text"]
    assert "9876543210" not in res["sanitized_text"]
    assert "9845012345" not in res["sanitized_text"]


def test_ten_indian_clinical_notes_suite(masker):
    sample_notes = [
        "Patient Priya Sharma, 34F, ABHA ID 91-4820-9182-4412, Phone: +91 9876543210. Complaints of severe persistent headache for 3 days and blood pressure 140/90 mmHg.",
        "Consultation with Mr. Ramesh Gupta from Indiranagar Bangalore 560038, Mobile 9845012345, Aadhaar 4920 1823 9912. Diagnosed with Type 2 Diabetes Mellitus.",
        "Smt. Sunita Devi, ABHA handle sunita.devi@abdm, Contact +91-9123456789. Prescribed Metformin 500mg 1-0-1 after food.",
        "Pt. Vikram Patel, DOB 15/08/1985, Aadhaar 5829-1029-4410, phone 09820192834. Presenting with acute dry cough and fever for 4 days.",
        "Patient is Rajesh Kumar, living in Saket New Delhi 110017. ABHA: 14-9912-3841-7782. Advised Tab Telmisartan 40mg once daily in the morning.",
        "Baby of Pooja Rao, 6 months old, father mobile +91 9988776655, resident of Andheri Mumbai. Routine pediatric immunization completed.",
        "Dr. Sunil Deshmukh examined Ananya Mukherjee, ABHA 88120455193321, Phone: 8877665544. Fasting blood sugar 160 mg/dL, HbA1c 7.8%.",
        "Follow up for Mr. Amit Shah, Aadhaar 9182 7364 5019, Call: +91 9811223344. Advised low sodium diet and brisk walking 30 mins daily.",
        "Patient Kavita Reddy, ABHA handle kavita.reddy@sbx, Phone: 9700112233. Complaining of bilateral knee joint pain on climbing stairs.",
        "Pt named Mohammad Irfan, phone +91 9654321098, Aadhaar: 3124 5678 9012, pin 700001 Kolkata. Diagnosed with Acute Bronchitis."
    ]

    for idx, note in enumerate(sample_notes, 1):
        res = masker.mask(note)
        sanitized = res["sanitized_text"]
        
        # Verify 0% leak of raw phone, ABHA, or Aadhaar
        assert not re.search(r"\b\d{2}-\d{4}-\d{4}-\d{4}\b", sanitized), f"Note {idx} leaked ABHA ID!"
        assert not re.search(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b", sanitized), f"Note {idx} leaked Aadhaar!"
        assert not re.search(r"\b[6-9]\d{9}\b", sanitized), f"Note {idx} leaked phone number!"
        assert res["pii_detected"] is True
        assert len(res["redacted_spans"]) > 0
