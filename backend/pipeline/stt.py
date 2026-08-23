"""
Realtime Speech-to-Text Pipeline

Integrates faster-whisper with Native Silero VAD for offline-first,
zero-trust transcription via WebSocket streaming.

Optimized for Indian-accented English, Indian clinical pharmaceuticals (Dolo 650,
Paracetamol, Metformin, etc.), numerical digit formatting for PII detection,
and aggressive rural clinic ambient noise rejection.

Hallucination suppression is applied at four independent layers:
  1. Whisper decoder parameters (no_speech_threshold, compression_ratio_threshold)
  2. Per-segment avg_log_prob confidence gate (drops low-confidence gibberish segments)
  3. Known hallucination phrase blocklist (catches Whisper's most common fantasies)
  4. RMS energy floor (stops inference on ambient AC hum / keyboard noise)
"""

import os
import re
import logging
from typing import Optional
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps

logger = logging.getLogger(__name__)

# Default model size and compute settings
# Tuned for laptop-class hardware: i5-12450HX (12 threads, 15GB RAM).
# int8_float32: weights stored in int8 (low RAM), activations in float32 (better accuracy than
# pure int8). int8_float16 is CUDA-only — int8_float32 is the correct CPU equivalent.
# 8 cpu_threads: leaves 4 threads free for the OS, browser, and Vite dev server.
_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small.en")
_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8_float32")
_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "8"))

DEFAULT_INDIAN_CLINICAL_PROMPT = (
    "Clinical consultation notes in Indian English. Patient vitals: BP 120/80, pulse 72, SpO2 98. "
    "Prescription: Dolo 650, Paracetamol, Metformin, Amlodipine, Pantocid, Augmentin, Azithromycin, Cetirizine."
)

# ---------------------------------------------------------------------------
# Hallucination blocklist
# Whisper tends to hallucinate these exact phrases when processing silence or
# faint background noise. Any segment matching these patterns is dropped.
# ---------------------------------------------------------------------------
_HALLUCINATION_PATTERNS: list[re.Pattern] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"^\s*thank you very much[\.!,]?\s*$",              # "Thank you very much."
        r"^\s*thank(s| you)[\.!,]?\s*$",                  # "Thanks.", "Thank you."
        r"^\s*thanks for watching[\.!]?\s*$",
        r"^\s*thanks for listening[\.!]?\s*$",
        r"^\s*please subscribe[\.!]?\s*$",
        r"^\s*like and subscribe[\.!]?\s*$",
        r"^\s*don'?t forget to subscribe[\.!]?\s*$",
        r"^\s*(\.\.\.|…|\-+)\s*$",                         # "...", "---"
        r"^\s*\[\s*(music|applause|laughter|noise|silence)\s*\]\s*$",  # [Music]
        r"^\s*\(\s*(music|applause|laughter)\s*\)\s*$",   # (Music)
        r"^\s*subtitles by.+$",
        r"^\s*transcript by.+$",
        r"^\s*captions by.+$",
        r"(.)\1{6,}",                                       # "aaaaaaaaaa" repeated chars
        r"^\s*(um+|uh+|hmm+|ah+)\s*[\.!]?\s*$",           # pure filler with nothing else
        r"^\s*www\..+$",                                   # URLs
        r"^\s*copyright.+$",
        r"^\s*all rights reserved[\.!]?\s*$",
        r"^\s*end of (video|recording|session)[\.!]?\s*$",
    ]
]

# Minimum avg log-probability per token for a segment to be considered real speech.
# Whisper returns ~log(1/vocab_size) ≈ -4.6 for random tokens — genuine speech
# sits around -0.2 to -0.8. Indian-accented English with fast inter-word cadence
# can score down to -1.2, so we gate at that value.
_MIN_AVG_LOG_PROB: float = float(os.getenv("WHISPER_MIN_LOG_PROB", "-1.2"))

# RMS floor: minimum signal energy required to even attempt transcription.
# 0.005 filters AC hum and fan noise while accepting a laptop mic at normal
# speaking distance (typical normalised RMS: 0.015–0.060).
_RMS_FLOOR: float = float(os.getenv("WHISPER_RMS_FLOOR", "0.005"))

# ---------------------------------------------------------------------------
# Weaponized demo-seeded initial_prompt
#
# Whisper uses initial_prompt as fake "previous context" to bias its
# attention heads before decoding starts. By loading every patient name,
# exact drug name, ICD term, and vital from the demo queue into this string,
# we prime the model's token distribution. When the doctor says "pregabalin"
# or "Rahul", the beam search is already pointing at those tokens.
#
# Demo patients: Rahul Sharma, Meena Devi, Arjun Kumar, Lakshmi Bai,
#                Ibrahim Sheikh, Sunita Rani
# Demo drugs:    Paracetamol 650, Metformin 500/1000, Pregabalin 75,
#                Salbutamol, Budesonide 100, IFA, Calcium 500, Aspirin 75,
#                Atorvastatin 20, Sorbitrate, Naproxen 250, Amlodipine 5,
#                ORS, Dolo 650, Augmentin, Azithromycin
# ---------------------------------------------------------------------------
DEMO_SEEDED_PROMPT = (
    "Doctor dictation, Indian English, outpatient clinic. "
    "Patient Rahul Sharma, thirty four year old male, fever three days, paracetamol six fifty, ORS, dengue NS1. "
    "Patient Meena Devi, fifty two year old female, type two diabetes, metformin one thousand, pregabalin seventy five, HbA1c. "
    "Patient Arjun Kumar, seven year old male, wheeze, salbutamol inhaler, budesonide hundred micrograms. "
    "Patient Lakshmi Bai, twenty eight year old female, antenatal twenty four weeks, iron folic acid, calcium five hundred. "
    "Patient Ibrahim Sheikh, sixty one year old male, chest tightness, aspirin seventy five, atorvastatin twenty, sorbitrate sublingual, amlodipine. "
    "Patient Sunita Rani, forty five year old female, joint pain, naproxen two fifty, rheumatoid factor, anti CCP. "
    "Vitals: BP 120 over 80, pulse 72, SpO2 98, temperature 101.4 Fahrenheit, respiratory rate 26. "
    "Impression: acute viral febrile illness, type two diabetes mellitus, peripheral neuropathy, "
    "episodic asthma, stable angina, inflammatory polyarthritis."
)


def build_clinical_prompt(patient_name: str = "", complaint: str = "") -> str:
    """Builds a demo-seeded initial_prompt conditioned on the active patient.

    The base prompt (DEMO_SEEDED_PROMPT) biases Whisper's attention toward
    every drug, name, and term present in the demo queue. The patient-specific
    prefix adds a second bias layer for the current active patient so their
    name and chief complaint are the most recently seen tokens — i.e., the
    highest-probability tokens in the attention head when decoding starts.
    """
    parts = []
    if patient_name and patient_name.strip():
        parts.append(f"Patient: {patient_name.strip()}.")
    if complaint and complaint.strip():
        parts.append(f"Chief complaint: {complaint.strip()}.")
    parts.append(DEMO_SEEDED_PROMPT)
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
        # Balanced VAD — filters dead air and fan noise without cutting Indian-accented speech.
        #
        # threshold=0.45     — Slightly below Silero default (0.5) to catch softer voices.
        # min_speech_duration_ms=100  — Accept phrases as short as 100ms ("BP" / "yes").
        # min_silence_duration_ms=500 — Wait 500ms of silence before closing a segment.
        #                               Longer pauses between Indian English words won't
        #                               cause premature segment splits.
        # speech_pad_ms=120  — 120ms padding around speech edges to catch word onsets.
        self.vad_parameters = dict(
            threshold=0.45,
            min_speech_duration_ms=100,
            min_silence_duration_ms=500,
            speech_pad_ms=120,
        )
        logger.info("STT pipeline ready — demo-seeded prompt + balanced VAD loaded.")

    def transcribe_segment(
        self,
        audio_np: np.ndarray,
        initial_prompt: Optional[str] = None
    ) -> str:
        """
        Run faster-whisper on a Float32 NumPy array at 16 000 Hz mono.
        Returns the stripped transcript string, or "" for silence/noise.

        Hallucination suppression is applied at four layers:
          Layer 1 — RMS energy floor (has_speech)
          Layer 2 — Whisper decoder thresholds (no_speech_threshold, compression_ratio_threshold)
          Layer 3 — Per-segment avg_log_prob confidence gate
          Layer 4 — Known hallucination phrase blocklist
        """
        if audio_np.size == 0 or not self.has_speech(audio_np):
            return ""

        prompt = initial_prompt or DEMO_SEEDED_PROMPT

        # Layer 2: Hardened decoder — no guessing, no fallback, no randomness.
        #
        # temperature=0.0 (scalar float, NOT a list)
        #   faster-whisper/Whisper accept either a float or a list of floats for temperature
        #   fallback. Passing a plain 0.0 scalar disables the fallback chain entirely.
        #   When Whisper fails at temperature 0 it returns empty — not hallucinated garbage.
        #   NEVER pass [0.0, 0.2, 0.4] — each fallback step is a random walk into fiction.
        #
        # no_speech_threshold=0.65
        #   Whisper's no_speech_prob for real microphone speech (even quiet) typically lands
        #   between 0.40 and 0.70. At 0.80 we were dropping legitimate voice. 0.65 still
        #   blocks clear silence and fan noise hum (which scores 0.85+).
        #
        # log_prob_threshold=-1.2
        #   Indian English at natural pace scores avg_logprob ~-0.8 to -1.2. Previous
        #   -1.0 was cutting off fast or accented speech at the decoder level.
        #
        # compression_ratio_threshold=1.9
        #   Loops still compress better than real speech. 1.9 is tight without being
        #   so tight that real repetitive medical language ("BP, BP 120 over 80") gets dropped.
        segments, _info = self.model.transcribe(
            audio_np,
            language="en",
            vad_filter=True,
            vad_parameters=self.vad_parameters,
            beam_size=2,
            temperature=0.0,             # scalar — disables fallback chain entirely
            initial_prompt=prompt,
            condition_on_previous_text=False,
            compression_ratio_threshold=1.9,
            no_speech_threshold=0.65,          # was 0.80 — too aggressive for real mic input
            log_prob_threshold=-1.2,           # was -1.0 — too tight for Indian accent
        )

        # Layer 3 + 4: Per-segment confidence gate and phrase blocklist
        clean_parts: list[str] = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue

            # Layer 3: avg_log_prob gate — hallucinated segments score very low
            if hasattr(seg, "avg_logprob") and seg.avg_logprob < _MIN_AVG_LOG_PROB:
                logger.debug(
                    "Dropped low-confidence segment (avg_logprob=%.3f): %r",
                    seg.avg_logprob, text
                )
                continue

            # Layer 4: known hallucination phrase blocklist
            if any(pat.search(text) for pat in _HALLUCINATION_PATTERNS):
                logger.debug("Dropped hallucination phrase: %r", text)
                continue

            clean_parts.append(text)

        return " ".join(clean_parts).strip()

    def has_speech(self, audio_np: np.ndarray) -> bool:
        """
        Layer 1 hallucination gate: Fast energy check.
        Returns True only if the audio RMS is above the configured noise floor.

        The floor is intentionally higher than a whisper to filter out:
          - AC / fan background hum
          - Keyboard / mouse click transients
          - Microphone self-noise and breath
        """
        if audio_np.size == 0:
            return False
        rms = float(np.sqrt(np.mean(audio_np ** 2)))
        return rms >= _RMS_FLOOR


# Lazy singleton — instantiated once at first WebSocket connection, not at import
# time, to avoid blocking the main process during model download.
_stt_instance: RealtimeSTT | None = None


def get_stt_engine() -> RealtimeSTT:
    """Return the module-level singleton, creating it on first call."""
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = RealtimeSTT()
    return _stt_instance

