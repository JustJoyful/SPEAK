"""Local Edge PII Masking Engine using Microsoft Presidio and Custom Indian Recognizers.

Zero-Trust Rule: All clinical transcripts and notes MUST be stripped of direct PII
(ABHA IDs, Aadhaar numbers, phone numbers, patient names, dates of birth, addresses)
BEFORE being transmitted to any cloud LLM or external service.
"""

import re
import logging
from typing import Dict, Any, List, Optional
from presidio_analyzer import (
    AnalyzerEngine,
    Pattern,
    PatternRecognizer,
    RecognizerResult
)
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger("medsync.pii_mask")


def build_analyzer_engine() -> AnalyzerEngine:
    """Builds and initializes the Presidio AnalyzerEngine with custom Indian healthcare recognizers."""
    # Attempt to configure spaCy NLP engine (fall back gracefully)
    nlp_config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }
    
    try:
        provider = NlpEngineProvider(nlp_configuration=nlp_config)
        nlp_engine = provider.create_engine()
        analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    except Exception as e:
        logger.warning(f"Could not load custom NlpEngineProvider ({e}), falling back to default AnalyzerEngine")
        analyzer = AnalyzerEngine()

    # 1. Custom Recognizer: ABHA ID (14 digits, e.g. 91-4820-9182-4412 or 91482091824412) and ABHA Address (@abdm, @sbx)
    abha_patterns = [
        Pattern(
            name="abha_number_pattern",
            regex=r"\b\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
            score=0.85
        ),
        Pattern(
            name="abha_address_pattern",
            regex=r"\b[a-zA-Z0-9.\-_]{3,}@(abdm|sbx|ndhm|abha)\b",
            score=0.90
        )
    ]
    abha_recognizer = PatternRecognizer(
        supported_entity="ABHA_ID",
        patterns=abha_patterns,
        context=["abha", "health id", "abdm", "phr", "ndhm", "patient id"]
    )
    analyzer.registry.add_recognizer(abha_recognizer)

    # 2. Custom Recognizer: Aadhaar Number (12 digits, starts with 2-9)
    aadhaar_patterns = [
        Pattern(
            name="aadhaar_pattern",
            regex=r"\b[2-9]\d{3}[-\s]?\d{4}[-\s]?\d{4}\b",
            score=0.85
        )
    ]
    aadhaar_recognizer = PatternRecognizer(
        supported_entity="AADHAAR_NUMBER",
        patterns=aadhaar_patterns,
        context=["aadhaar", "aadhar", "uidai", "uid", "identity"]
    )
    analyzer.registry.add_recognizer(aadhaar_recognizer)

    # 3. Custom Recognizer: Indian Phone Numbers (+91 or 10 digits starting with 6-9)
    phone_patterns = [
        Pattern(
            name="indian_phone_full",
            regex=r"\b(?:\+91[-\s]?|91[-\s]?|0)?[6-9]\d{4}[-\s]?\d{5}\b",
            score=0.80
        ),
        Pattern(
            name="indian_phone_10digit",
            regex=r"\b(?:\+91[-\s]?|0)?[6-9]\d{9}\b",
            score=0.80
        )
    ]
    phone_recognizer = PatternRecognizer(
        supported_entity="PHONE_NUMBER",
        patterns=phone_patterns,
        context=["phone", "mobile", "contact", "call", "tel", "cell", "number"]
    )
    analyzer.registry.add_recognizer(phone_recognizer)

    # 4. Custom Recognizer: Indian PIN Code (6 digits)
    pincode_patterns = [
        Pattern(
            name="indian_pincode",
            regex=r"\b[1-9][0-9]{2}\s?[0-9]{3}\b",
            score=0.60
        )
    ]
    pincode_recognizer = PatternRecognizer(
        supported_entity="PINCODE",
        patterns=pincode_patterns,
        context=["pin", "pincode", "postal", "zip", "area", "address"]
    )
    analyzer.registry.add_recognizer(pincode_recognizer)

    # 5. Regex Fallback for Indian Name Honorifics (e.g. Mr. Rajesh Kumar, Smt. Sunita Devi)
    # Using negative lookahead to prevent matching clinical verbs like Advised, Prescribed, Diagnosed
    honorific_patterns = [
        Pattern(
            name="indian_honorific_name",
            regex=r"\b(?:Mr\.|Mrs\.|Ms\.|Shri|Smt\.|Master|Baby\s+of)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
            score=0.85
        ),
        Pattern(
            name="patient_name_prefix",
            regex=r"\b(?:Patient|patient|Pt\.?)\s+(?:is\s+|name\s+is\s+|named\s+)?(?!Advised|Prescribed|Diagnosed|Reports|Presenting|Complaining)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
            score=0.85
        )
    ]
    honorific_recognizer = PatternRecognizer(
        supported_entity="PERSON",
        patterns=honorific_patterns,
        context=["patient", "consultation", "examination", "pt", "mr", "mrs", "ms", "shri", "smt"]
    )
    analyzer.registry.add_recognizer(honorific_recognizer)

    return analyzer


# Clinical dictionary to protect from over-zealous NER misclassifications
PROTECTED_CLINICAL_TERMS = {
    "tab", "tablet", "cap", "capsule", "inj", "injection", "syrup", "ointment",
    "advised", "prescribed", "diagnosed", "reports", "presenting", "complaining",
    "acute", "chronic", "bronchitis", "diabetes", "hypertension", "mellitus",
    "fever", "cough", "headache", "pain", "blood pressure", "sugar", "hba1c",
    "asthma", "pneumonia", "gastritis", "metformin", "paracetamol", "telmisartan",
    "amoxicillin", "atorvastatin", "amlodipine", "azithromycin", "insulin",
    "normal", "elevated", "critical", "daily", "sos", "after food", "before food"
}


class PIIMasker:
    """Zero-Trust PII Masking Engine for Edge Node Processing."""

    def __init__(self, analyzer: Optional[AnalyzerEngine] = None):
        self.analyzer = analyzer or build_analyzer_engine()
        self.anonymizer = AnonymizerEngine()

    def analyze(self, text: str, min_score: float = 0.4) -> List[RecognizerResult]:
        """Analyzes text for PII entities while protecting critical clinical vocabulary."""
        if not text or not text.strip():
            return []

        results = self.analyzer.analyze(
            text=text,
            language="en",
            score_threshold=min_score,
            entities=[
                "PERSON",
                "PHONE_NUMBER",
                "EMAIL_ADDRESS",
                "LOCATION",
                "DATE_TIME",
                "ABHA_ID",
                "AADHAAR_NUMBER",
                "PINCODE",
                "MEDICAL_LICENSE",
                "IP_ADDRESS",
                "US_SSN"
            ]
        )

        filtered_results = []
        for r in results:
            span_text = text[r.start:r.end].strip().lower()
            # Protect clinical diagnoses/medications from being accidentally masked as PERSON or LOCATION
            if r.entity_type in ["PERSON", "LOCATION"] and (
                span_text in PROTECTED_CLINICAL_TERMS or
                any(term in span_text for term in ["bronchitis", "diabetes", "hypertension", "asthma", "pneumonia", "advised tab"])
            ):
                continue
            filtered_results.append(r)

        return filtered_results

    def mask(self, text: str, min_score: float = 0.4) -> Dict[str, Any]:
        """Sanitizes text and returns redacted spans for live X-Ray UI telemetry."""
        if not text or not text.strip():
            return {
                "original_text": text,
                "sanitized_text": text,
                "pii_detected": False,
                "redacted_spans": [],
                "entity_counts": {}
            }

        results = self.analyze(text, min_score=min_score)

        # Build redacted spans metadata for the frontend X-Ray visualizer
        redacted_spans = []
        entity_counts: Dict[str, int] = {}

        # Sort results descending by start to avoid index drift
        sorted_results = sorted(results, key=lambda x: x.start, reverse=True)

        for res in sorted_results:
            orig_val = text[res.start:res.end]
            entity_type = res.entity_type
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
            
            redacted_spans.append({
                "entity_type": entity_type,
                "start": res.start,
                "end": res.end,
                "original_text": orig_val,
                "replacement": f"<{entity_type}>",
                "confidence_score": round(res.score, 2)
            })

        # Anonymize text with entity replacement tags (e.g. <PERSON>, <ABHA_ID>, <PHONE_NUMBER>)
        operators = {
            "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
            "ABHA_ID": OperatorConfig("replace", {"new_value": "<ABHA_ID>"}),
            "AADHAAR_NUMBER": OperatorConfig("replace", {"new_value": "<AADHAAR_NUMBER>"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE_NUMBER>"}),
            "LOCATION": OperatorConfig("replace", {"new_value": "<LOCATION>"}),
            "PINCODE": OperatorConfig("replace", {"new_value": "<PINCODE>"}),
            "DATE_TIME": OperatorConfig("replace", {"new_value": "<DATE_TIME>"}),
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL_ADDRESS>"}),
            "MEDICAL_LICENSE": OperatorConfig("replace", {"new_value": "<MEDICAL_LICENSE>"}),
            "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"})
        }

        anonymized = self.anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators
        )

        sanitized_text = anonymized.text

        # Secondary regex pass for edge cases (e.g. standalone phone or Aadhaar not caught by NLP threshold)
        sanitized_text = re.sub(
            r"\b\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
            "<ABHA_ID>",
            sanitized_text
        )
        sanitized_text = re.sub(
            r"\b[2-9]\d{3}[-\s]?\d{4}[-\s]?\d{4}\b",
            "<AADHAAR_NUMBER>",
            sanitized_text
        )
        sanitized_text = re.sub(
            r"\b(?:\+91[-\s]?|0)?[6-9]\d{9}\b",
            "<PHONE_NUMBER>",
            sanitized_text
        )

        return {
            "original_text": text,
            "sanitized_text": sanitized_text,
            "pii_detected": len(results) > 0 or sanitized_text != text,
            "redacted_spans": list(reversed(redacted_spans)),
            "entity_counts": entity_counts
        }

    def strip_all_pii(self, text: str) -> str:
        """Returns exclusively the sanitized text string."""
        return self.mask(text)["sanitized_text"]


# Global singleton instance for high-throughput pipeline execution
global_pii_masker = PIIMasker()


def mask_pii(text: str) -> Dict[str, Any]:
    """Convenience function for PII masking."""
    return global_pii_masker.mask(text)
