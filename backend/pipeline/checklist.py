from typing import Tuple, Optional
from backend.pipeline.fhir_schema import ChecklistState
from backend.pipeline.pii_mask import mask_pii

async def extract_checklist(clinical_text: str, api_key: Optional[str] = None) -> Tuple[Optional[ChecklistState], str]:
    """
    Evaluates the presence of clinical components in the text using local GLiNER edge node.
    Returns the validated ChecklistState and any error diagnostics (empty string if success).
    """
    if not clinical_text or not clinical_text.strip():
        # Empty text means nothing is present
        return ChecklistState(), ""

    try:
        # Run the zero-latency local GLiNER pipeline
        result = mask_pii(clinical_text)
        entities = result.get("clinical_entities", [])
        
        state = ChecklistState(
            symptoms_present=False,
            diagnosis_present=False,
            medication_present=False,
            advice_present=False
        )
        
        for ent in entities:
            label = ent.get("label", "")
            if label == "SYMPTOM":
                state.symptoms_present = True
            elif label == "DISEASE":
                state.diagnosis_present = True
            elif label == "MEDICATION":
                state.medication_present = True
            elif label == "ADVICE":
                state.advice_present = True
                
        return state, ""
        
    except Exception as e:
        return None, f"Unexpected error during GLiNER checklist extraction: {str(e)}"
