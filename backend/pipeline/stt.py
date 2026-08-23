"""
Realtime Speech-to-Text Pipeline

Integrates faster-whisper with Native Silero VAD for offline-first,
zero-trust transcription via WebSocket streaming.

Optimized for Indian-accented English, Indian clinical pharmaceuticals (Dolo 650,
Paracetamol, Metformin, etc.), numerical digit formatting for PII detection,
and aggressive rural clinic ambient noise rejection.
"""

import os
import logging
from typing import Optional
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps

logger = logging.getLogger(__name__)

# Default model size and compute settings
_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small.en")
_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "4"))

DEFAULT_INDIAN_CLINICAL_PROMPT = (
    "Doctor in India dictating OP clinical consultation: Patient presents with fever, chills, "
    "cough, headache, body ache, chest pain, diabetes, hypertension. Vitals: BP 120/80 mmHg, "
    "Pulse 72 bpm, SpO2 98%, Temp 101.4 F, RBS 168 mg/dL. Rx: Dolo 650, Paracetamol 650mg TDS, "
    "Metformin 1000mg BD, Amlodipine 5mg OD, Pantocid 40mg, Augmentin 625mg, Azithromycin 500mg, "
    "Salbutamol inhaler 2 puffs PRN, Budesonide 100mcg BD, Pregabalin 75mg HS, ORS sachets ad lib. "
    "Investigations: CBC, Dengue NS1, HbA1c, Serum Creatinine, ECG, Urine routine. "
    "Contact: +91 9876543210. Aadhaar: 2345 6789 0123. Location: PHC Kolar, Ward 4."
)


def build_clinical_prompt(patient_name: str = "", complaint: str = "") -> str:
    """Builds dynamic initial_prompt conditioned on active patient context."""
    prefix_parts = []
    if patient_name and patient_name.strip():
        prefix_parts.append(f"Patient: {patient_name.strip()}.")
    if complaint and complaint.strip():
        prefix_parts.append(f"Chief Complaint: {complaint.strip()}.")
    if prefix_parts:
        return f"{' '.join(prefix_parts)} {DEFAULT_INDIAN_CLINICAL_PROMPT}"
    return DEFAULT_INDIAN_CLINICAL_PROMPT


class RealtimeSTT:
    def __init__(
        self,
        model_size: str = _MODEL_SIZE,
        compute_type: str = _COMPUTE_TYPE,
        cpu_threads: int = _CPU_THREADS
    ):
        logger.info(
            "Loading faster-whisper model (%s, compute_type=%s, cpu_threads=%d) on CPU …",
            model_size,
            compute_type,
            cpu_threads
        )
        # int8 quantisation keeps RAM low (<800MB) on legacy edge hardware
        self.model = WhisperModel(
            model_size,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=cpu_threads
        )
        # Tuned Silero VAD options for noisy PHC clinic environments
        self.vad_options = VadOptions(
            threshold=0.5,
            min_speech_duration_ms=250,
            min_silence_duration_ms=800,
            speech_pad_ms=300
        )
        logger.info("STT pipeline ready for Indian clinical dictation.")

    def transcribe_segment(
        self,
        audio_np: np.ndarray,
        initial_prompt: Optional[str] = None
    ) -> str:
        """
        Run faster-whisper on a Float32 NumPy array at 16 000 Hz mono.
        Returns the stripped transcript string, or "" for silence/noise.
        """
        if audio_np.size == 0:
            return ""

        prompt = initial_prompt or DEFAULT_INDIAN_CLINICAL_PROMPT

        segments, _info = self.model.transcribe(
            audio_np,
            vad_filter=False,  # We apply Silero VAD before calling transcribe
            beam_size=1,       # Greedy decoding for real-time responsiveness
            temperature=0.0,
            initial_prompt=prompt,
            condition_on_previous_text=False,  # Avoid runaway hallucination loops
            compression_ratio_threshold=2.4,   # Suppress repetitive noise loops
            no_speech_threshold=0.6,          # Drop background chatter
        )
        return " ".join(s.text for s in segments).strip()

    def has_speech(self, audio_np: np.ndarray) -> bool:
        """
        Return True if Silero VAD detects at least one speech segment.
        Correct call: get_speech_timestamps(audio, vad_options, sampling_rate).
        """
        if audio_np.size == 0:
            return False
        timestamps = get_speech_timestamps(
            audio_np,
            self.vad_options,
            sampling_rate=16000,
        )
        return bool(timestamps)


# Lazy singleton — instantiated once at first WebSocket connection, not at import
# time, to avoid blocking the main process during model download.
_stt_instance: RealtimeSTT | None = None


def get_stt_engine() -> RealtimeSTT:
    """Return the module-level singleton, creating it on first call."""
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = RealtimeSTT()
    return _stt_instance

