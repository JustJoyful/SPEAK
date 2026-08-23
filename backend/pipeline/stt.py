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
    "Clinical consultation notes in Indian English. Patient vitals: BP 120/80, pulse 72, SpO2 98. "
    "Prescription: Dolo 650, Paracetamol, Metformin, Amlodipine, Pantocid, Augmentin, Azithromycin, Cetirizine."
)


def build_clinical_prompt(patient_name: str = "", complaint: str = "") -> str:
    """Builds concise dynamic initial_prompt conditioned on active patient context."""
    parts = []
    if patient_name and patient_name.strip():
        parts.append(f"Patient: {patient_name.strip()}.")
    if complaint and complaint.strip():
        parts.append(f"Chief complaint: {complaint.strip()}.")
    parts.append(DEFAULT_INDIAN_CLINICAL_PROMPT)
    return " ".join(parts)


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
        # Sane VAD parameters for continuous live clinical audio streaming
        self.vad_parameters = dict(
            threshold=0.35,
            min_speech_duration_ms=120,
            min_silence_duration_ms=400,
            speech_pad_ms=200
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
        if audio_np.size == 0 or not self.has_speech(audio_np):
            return ""

        prompt = initial_prompt or DEFAULT_INDIAN_CLINICAL_PROMPT

        segments, _info = self.model.transcribe(
            audio_np,
            language="en",     # Enforce English decoding (prevents misidentifying Indian accents as Hindi/Welsh)
            vad_filter=True,   # Native Silero VAD integrated inside faster-whisper
            vad_parameters=self.vad_parameters,
            beam_size=2,        # Beam search for superior phonetic accuracy
            temperature=0.0,
            initial_prompt=prompt,
            condition_on_previous_text=False,  # Avoid runaway hallucination loops
            compression_ratio_threshold=2.4,   # Suppress repetitive noise loops
            no_speech_threshold=0.6,          # Drop background chatter
        )
        return " ".join(s.text for s in segments).strip()

    def has_speech(self, audio_np: np.ndarray) -> bool:
        """
        Fast energy check: Returns True if audio contains audible signal above noise floor.
        """
        if audio_np.size == 0:
            return False
        rms = float(np.sqrt(np.mean(audio_np ** 2)))
        return rms >= 0.002


# Lazy singleton — instantiated once at first WebSocket connection, not at import
# time, to avoid blocking the main process during model download.
_stt_instance: RealtimeSTT | None = None


def get_stt_engine() -> RealtimeSTT:
    """Return the module-level singleton, creating it on first call."""
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = RealtimeSTT()
    return _stt_instance

