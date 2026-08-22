import os
import json
import httpx
from typing import Dict, Any, Tuple, Optional
from pydantic import ValidationError

from backend.pipeline.fhir_schema import FHIROPConsultRecord

SYSTEM_PROMPT = """You are a medical AI assistant. Your task is to extract clinical information from the provided doctor's dictation or notes, and format it strictly as a JSON object adhering to the NRCeS FHIR R4 Outpatient (OP) Consultation Record format.

Ensure you map the extracted information to the following keys:
- "chief_complaints": list of strings
- "vitals": list of objects with "vital_name", "value", and optional "interpretation"
- "diagnoses": list of objects with "clinical_status" (active/resolved/etc), "verification_status" (provisional/confirmed/etc), "code" (having "coding" list and "text" string), and optional "notes"
- "medications": list of objects with "medication" (having "coding" list and "text" string), "dosage" (having "timing", "duration", "route", "instructions"), and optional "reason"
- "advice_and_followup": string or null

Do NOT include any patient identifiable information like names, phone numbers, or ABHA IDs. Only include clinical data.
Return ONLY valid JSON. Do not include markdown formatting like ```json.
"""

def inject_care_context(parsed_json: Dict[str, Any], care_context_id: str) -> Dict[str, Any]:
    """Auto-injects the local Care-Context ID into the structured JSON to enforce zero-trust bounds."""
    parsed_json["subject"] = {
        "reference": f"CareContext/{care_context_id}",
        "display": "Anonymous Patient Context"
    }
    return parsed_json

def _mock_sadiesink(clinical_text: str, care_context_id: str) -> "FHIROPConsultRecord":
    """
    Local rule-based FHIR structurer — used when no LLM API key is configured.
    Produces a plausible bundle from keyword/regex extraction so the demo is
    fully self-contained without cloud API access.
    """
    import re
    text_lower = clinical_text.lower()

    # Chief complaints: sentences containing symptom keywords
    symptom_kws = ["pain", "fever", "cough", "cold", "headache", "nausea", "vomit",
                   "weakness", "fatigue", "breathless", "dizzy", "swelling", "rash",
                   "diarrhea", "constipation", "burning", "itching"]
    complaints = [kw.capitalize() for kw in symptom_kws if kw in text_lower] or ["General consultation"]

    # Medications: words near dose/frequency signals
    meds_re = re.compile(
        r"\b(tablet|tab|capsule|cap|syrup|injection|inj|ointment|drop)s?\s+(\w+)"
        r"|\b(\w+)\s+(tablet|tab|capsule|cap|syrup|injection|inj)s?\b",
        re.IGNORECASE,
    )
    med_names = list({m.group(2) or m.group(3) for m in meds_re.finditer(clinical_text) if (m.group(2) or m.group(3))})

    medications = [
        {
            "medication": {"coding": [], "text": name.capitalize()},
            "dosage": {"timing": "As directed", "duration": "5 days", "route": "oral", "instructions": "Take as prescribed"},
        }
        for name in med_names[:5]
    ]

    # Diagnoses: simple keyword match
    diagnosis_kws = {
        "fever": "Pyrexia", "infection": "Infection, unspecified", "cold": "Common cold",
        "cough": "Acute cough", "hypertension": "Hypertension", "diabetes": "Diabetes mellitus",
        "pneumonia": "Pneumonia", "asthma": "Asthma", "anemia": "Anaemia",
    }
    diags = [
        {"clinical_status": "active", "verification_status": "provisional",
         "code": {"coding": [], "text": label}, "notes": None}
        for kw, label in diagnosis_kws.items() if kw in text_lower
    ] or [{"clinical_status": "active", "verification_status": "provisional",
            "code": {"coding": [], "text": "Presenting complaint under evaluation"}, "notes": None}]

    bundle_dict = {
        "subject": {"reference": f"CareContext/{care_context_id}", "display": "Anonymous Patient Context"},
        "chief_complaints": complaints[:5],
        "vitals": [],
        "diagnoses": diags[:4],
        "medications": medications,
        "advice_and_followup": "Follow up after 5 days or sooner if symptoms worsen. Take rest and maintain hydration.",
    }
    return FHIROPConsultRecord.model_validate(bundle_dict)


async def sadiesink(clinical_text: str, care_context_id: str, api_key: "Optional[str]" = None) -> "Tuple[Optional[FHIROPConsultRecord], str]":
    """
    Calls an LLM to structure clinical text into a FHIR R4 bundle.
    Falls back to a local mock structurer when no API key is configured,
    so the demo works fully offline / without cloud credentials.
    """
    api_key = api_key or os.getenv("LLM_API_KEY")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")

    # ── No API key — use local rule-based mock ────────────────────────────────
    if not deepseek_key and not api_key:
        try:
            record = _mock_sadiesink(clinical_text or "General consultation", care_context_id)
            return record, ""
        except Exception as e:
            return None, f"Mock structurer error: {e}"

    # ── Cloud LLM path ────────────────────────────────────────────────────────
    if deepseek_key:
        url = "https://api.deepseek.com/chat/completions"
        headers = {"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"}
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": clinical_text}],
            "temperature": 0.0,
        }
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": clinical_text}],
            "temperature": 0.0,
        }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            llm_output = data["choices"][0]["message"]["content"].strip()

            if llm_output.startswith("```json"):
                llm_output = llm_output[7:]
            if llm_output.endswith("```"):
                llm_output = llm_output[:-3]

            parsed_json = json.loads(llm_output)
            parsed_json = inject_care_context(parsed_json, care_context_id)
            record = FHIROPConsultRecord.model_validate(parsed_json)
            return record, ""

    except httpx.HTTPError as e:
        return None, f"HTTP Error during LLM call: {str(e)}"
    except json.JSONDecodeError as e:
        return None, f"JSON Decode Error from LLM response: {str(e)}"
    except ValidationError as e:
        return None, f"Pydantic Validation Error: {str(e)}"
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"

