import os
import json
import httpx
from typing import Tuple, Optional
from pydantic import ValidationError

from backend.pipeline.fhir_schema import ChecklistState

SYSTEM_PROMPT = """You are a medical AI assistant. Your task is to evaluate a partial or complete clinical transcript and determine which components of a standard clinical encounter are present.

Return ONLY a valid JSON object matching this schema:
{
    "symptoms_present": bool, // true if chief complaints or symptoms are mentioned
    "diagnosis_present": bool, // true if a diagnosis, provisional diagnosis, or clinical impression is mentioned
    "medication_present": bool, // true if any medication, drug, or prescription is mentioned
    "advice_present": bool // true if follow-up, advice, lifestyle instructions, or lab orders are mentioned
}

Do not include any markdown formatting like ```json.
"""

async def extract_checklist(clinical_text: str, api_key: Optional[str] = None) -> Tuple[Optional[ChecklistState], str]:
    """
    Calls an LLM to evaluate the presence of clinical components in the text.
    Validates the output against ChecklistState.
    Returns the validated model and any error diagnostics (empty string if success).
    """
    if not clinical_text or not clinical_text.strip():
        # Empty text means nothing is present
        return ChecklistState(), ""

    api_key = api_key or os.getenv("LLM_API_KEY")
    if not api_key:
        return None, "Error: LLM_API_KEY not provided."

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
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            llm_output = data["choices"][0]["message"]["content"].strip()
            
            # Remove markdown backticks if present
            if llm_output.startswith("```json"):
                llm_output = llm_output[7:]
            if llm_output.endswith("```"):
                llm_output = llm_output[:-3]
                
            parsed_json = json.loads(llm_output)
            
            # Pydantic schema validation gate
            record = ChecklistState.model_validate(parsed_json)
            return record, ""
            
    except httpx.HTTPError as e:
        return None, f"HTTP Error during LLM call: {str(e)}"
    except json.JSONDecodeError as e:
        return None, f"JSON Decode Error from LLM response: {str(e)}\nRaw Output: {llm_output}"
    except ValidationError as e:
        return None, f"Pydantic Validation Error: {str(e)}"
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"
