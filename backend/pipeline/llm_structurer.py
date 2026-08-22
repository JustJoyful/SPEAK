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
- "diagnoses": list of objects with "clinical_status" (active/resolved/etc), "verification_status" (provisional/confirmed/etc), "code" (having "coding" and "text"), and optional "notes"
- "medications": list of objects with "medication", "dosage" (having "timing", "duration", "route", "instructions"), and optional "reason"
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

async def sadiesink(clinical_text: str, care_context_id: str, api_key: Optional[str] = None) -> Tuple[Optional[FHIROPConsultRecord], str]:
    """
    Calls an LLM to structure clinical text into a FHIR R4 bundle.
    Validates the output against FHIROPConsultRecord.
    Returns the validated model and any error diagnostics (empty string if success).
    """
    # Real implementation using httpx (e.g., OpenAI API)
    api_key = api_key or os.getenv("LLM_API_KEY")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    
    if deepseek_key:
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {deepseek_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": clinical_text}
            ],
            "temperature": 0.0
        }
    elif api_key:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": clinical_text}
            ],
            "temperature": 0.0
        }
    else:
        return None, "Error: DEEPSEEK_API_KEY or LLM_API_KEY not provided."
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            llm_output = data["choices"][0]["message"]["content"].strip()
            
            # Remove markdown backticks if present
            if llm_output.startswith("```json"):
                llm_output = llm_output[7:]
            if llm_output.endswith("```"):
                llm_output = llm_output[:-3]
                
            parsed_json = json.loads(llm_output)
            parsed_json = inject_care_context(parsed_json, care_context_id)
            
            # Pydantic schema validation gate
            record = FHIROPConsultRecord.model_validate(parsed_json)
            return record, ""
            
    except httpx.HTTPError as e:
        return None, f"HTTP Error during LLM call: {str(e)}"
    except json.JSONDecodeError as e:
        return None, f"JSON Decode Error from LLM response: {str(e)}\nRaw Output: {llm_output}"
    except ValidationError as e:
        return None, f"Pydantic Validation Error: {str(e)}"
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"
