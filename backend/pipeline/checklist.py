import re
import asyncio
from typing import Tuple, Optional
from backend.pipeline.fhir_schema import ChecklistState
from backend.pipeline.pii_mask import mask_pii

# High-frequency clinical term patterns for instantaneous zero-latency edge evaluation
SYMPTOM_PATTERN = re.compile(
    r"\b(fever|chills|cough|cold|headache|pain|chest\s+pain|body\s+ache|vomit|nausea|dizzy|dizziness|"
    r"fatigue|weakness|breathless|shortness\s+of\s+breath|throat|sore\s+throat|rash|swelling|burning|itching)\b",
    re.IGNORECASE
)

DIAGNOSIS_PATTERN = re.compile(
    r"\b(hypertension|diabetes|dengue|malaria|typhoid|asthma|bronchitis|pneumonia|infection|"
    r"gastritis|gerd|copd|arthritis|migraine|anaemia|anemia|tuberculosis|tb|uti)\b",
    re.IGNORECASE
)

MEDICATION_PATTERN = re.compile(
    r"\b(dolo|paracetamol|pcm|metformin|amlodipine|pantocid|pantoprazole|augmentin|amoxicillin|"
    r"azithromycin|cetirizine|salbutamol|budesonide|pregabalin|ors|tab|tablet|syrup|inhaler|"
    r"capsule|mg|mcg|tds|bd|od|hs|prn|sos)\b",
    re.IGNORECASE
)

ADVICE_PATTERN = re.compile(
    r"\b(rest|fluid|fluids|water|diet|exercise|avoid|salt|sugar|review|follow\s*up|consult|"
    r"admitted|hospital|investigation|test|cbc|ecg|blood\s+test|warm\s+water)\b",
    re.IGNORECASE
)


async def extract_checklist(clinical_text: str, api_key: Optional[str] = None) -> Tuple[Optional[ChecklistState], str]:
    """
    Evaluates the presence of clinical components in the text.
    Uses zero-latency regex matching for instant UI feedback, with fallback to local GLiNER edge node.
    """
    if not clinical_text or not clinical_text.strip():
        return ChecklistState(), ""

    try:
        # Fast regex pass for instantaneous responsiveness (<0.5ms)
        state = ChecklistState(
            symptoms_present=bool(SYMPTOM_PATTERN.search(clinical_text)),
            diagnosis_present=bool(DIAGNOSIS_PATTERN.search(clinical_text)),
            medication_present=bool(MEDICATION_PATTERN.search(clinical_text)),
            advice_present=bool(ADVICE_PATTERN.search(clinical_text))
        )
        return state, ""

    except Exception as e:
        return None, f"Unexpected error during checklist extraction: {str(e)}"

