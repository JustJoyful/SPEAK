"""Local Edge PII Masking and Entity Extraction Engine using Native Regex + GLiNER.

Zero-Trust Rule: All clinical transcripts and notes MUST be stripped of direct PII
(ABHA IDs, Aadhaar numbers, phone numbers, patient names, PIN codes)
BEFORE being transmitted to any cloud LLM or external service.
"""

import re
import logging
from typing import Dict, Any, List

try:
    from gliner import GLiNER
except ImportError:
    GLiNER = None
    
logger = logging.getLogger("medsync.pii_mask")

class PIIMasker:
    """Zero-Trust Hybrid Masking Engine.
    Pass 1: Regex (ABHA, Aadhaar, Phone, PIN)
    Pass 2: GLiNER (Person, Clinical Entities)
    """

    def __init__(self):
        self.model = None
        self.labels = ["person", "symptom", "disease", "medication", "advice"]
        
    def load_model(self):
        """Loads the GLiNER model into memory for fast inference."""
        if GLiNER is None:
            logger.error("gliner package is not installed.")
            return
            
        if self.model is None:
            logger.info("Loading GLiNER model (gliner_small-v2.1)...")
            # Using gliner_small-v2.1 which uses ~500MB RAM
            self.model = GLiNER.from_pretrained("urchade/gliner_small-v2.1")
            logger.info("GLiNER model loaded successfully.")

    def _regex_pass(self, text: str) -> List[Dict[str, Any]]:
        """Pass 1: Regex Sniper for strict numeric PII."""
        spans = []
        
        # 1. ABHA ID (14 digits) and ABHA Address (@abdm, @sbx)
        abha_pattern = re.compile(r"\b\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")
        abha_address_pattern = re.compile(r"\b[a-zA-Z0-9.\-_]{3,}@(abdm|sbx|ndhm|abha)\b")
        # 2. Aadhaar Number (12 digits)
        aadhaar_pattern = re.compile(r"\b[2-9]\d{3}[-\s]?\d{4}[-\s]?\d{4}\b")
        # 3. Indian Phone Numbers
        phone_pattern = re.compile(r"\b(?:\+91[-\s]?|0)?[6-9]\d{9}\b")
        # 4. PIN Code
        pincode_pattern = re.compile(r"\b[1-9][0-9]{2}\s?[0-9]{3}\b")

        patterns = [
            ("ABHA_ID", abha_pattern),
            ("ABHA_ID", abha_address_pattern),
            ("AADHAAR_NUMBER", aadhaar_pattern),
            ("PHONE_NUMBER", phone_pattern),
            ("PINCODE", pincode_pattern)
        ]
        
        for entity_type, pattern in patterns:
            for match in pattern.finditer(text):
                orig_val = match.group()
                start = match.start()
                end = match.end()
                
                spans.append({
                    "entity_type": entity_type,
                    "start": start,
                    "end": end,
                    "original_text": orig_val,
                    "replacement": f"<{entity_type}>",
                    "confidence_score": 1.0,
                    "pass": "regex"
                })
        
        return spans

    def mask(self, text: str) -> Dict[str, Any]:
        """Hybrid two-pass pipeline for PII redaction and clinical concept extraction."""
        if not text or not text.strip():
            return {
                "original_text": text,
                "sanitized_text": text,
                "pii_detected": False,
                "redacted_spans": [],
                "entity_counts": {},
                "clinical_entities": []
            }

        # Ensure model is loaded (fallback if not called from lifespan)
        self.load_model()

        # Pass 1: Regex
        regex_spans = self._regex_pass(text)
        
        gliner_spans = []
        clinical_entities = []
        
        # Pass 2: GLiNER (applied to original text to get correct offsets, then we merge)
        if self.model:
            # Predict entities
            entities = self.model.predict_entities(text, self.labels, threshold=0.4)
            
            for ent in entities:
                label = ent["label"].upper()
                span_text = ent["text"]
                start = ent["start"]
                end = ent["end"]
                
                if label == "PERSON":
                    gliner_spans.append({
                        "entity_type": "PERSON",
                        "start": start,
                        "end": end,
                        "original_text": span_text,
                        "replacement": "<PERSON>",
                        "confidence_score": round(ent["score"], 2),
                        "pass": "gliner"
                    })
                elif label in ["SYMPTOM", "DISEASE", "MEDICATION", "ADVICE"]:
                    clinical_entities.append({
                        "label": label,
                        "text": span_text,
                        "score": round(ent["score"], 2)
                    })
                    
        # Unified replacement
        all_redactions = regex_spans + gliner_spans
        # Sort by start ascending to easily find overlaps
        all_redactions.sort(key=lambda x: x["start"])
        
        # Filter out overlapping spans (prioritize regex as they are strict)
        filtered_redactions = []
        for r in all_redactions:
            if not filtered_redactions:
                filtered_redactions.append(r)
            else:
                last = filtered_redactions[-1]
                # If overlap exists
                if r["start"] < last["end"]:
                    # Prioritize regex over gliner
                    if r["pass"] == "regex" and last["pass"] == "gliner":
                        filtered_redactions[-1] = r
                    elif r["pass"] == last["pass"]:
                        # Keep the longer one
                        if (r["end"] - r["start"]) > (last["end"] - last["start"]):
                            filtered_redactions[-1] = r
                    # Else keep the last one (which is regex, or earlier gliner)
                else:
                    filtered_redactions.append(r)
        
        # Now sort by start descending to replace without messing up early indices
        filtered_redactions.sort(key=lambda x: x["start"], reverse=True)
        
        final_text = text
        for redaction in filtered_redactions:
            start = redaction["start"]
            end = redaction["end"]
            rep = redaction["replacement"]
            final_text = final_text[:start] + rep + final_text[end:]

        # Entity counts
        entity_counts: Dict[str, int] = {}
        for r in filtered_redactions:
            e_type = r["entity_type"]
            entity_counts[e_type] = entity_counts.get(e_type, 0) + 1

        return {
            "original_text": text,
            "sanitized_text": final_text,
            "pii_detected": len(filtered_redactions) > 0,
            "redacted_spans": filtered_redactions,
            "entity_counts": entity_counts,
            "clinical_entities": clinical_entities
        }

    def strip_all_pii(self, text: str) -> str:
        """Returns exclusively the sanitized text string."""
        return self.mask(text)["sanitized_text"]


# Global singleton instance for high-throughput pipeline execution
global_pii_masker = PIIMasker()


def mask_pii(text: str) -> Dict[str, Any]:
    """Convenience function for PII masking."""
    return global_pii_masker.mask(text)
