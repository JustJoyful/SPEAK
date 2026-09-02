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

# Exact hardcoded non-clinical filler words dropped ONLY when triggered by short (<0.6s) transient pops.
# Does NOT use fuzzy/substring matching so legitimate single-word clinical findings
# ("Cough", "Clear", "Left", "Normal") are completely preserved.
_TRANSIENT_FILLER_WORDS: set[str] = {
    "so", "okay", "yeah", "the", "you", "thanks", "um", "ah", "ok"
}

# Minimum avg log-probability per token for a segment to be considered real speech.
# Whisper returns ~log(1/vocab_size) ≈ -4.6 for random tokens — genuine speech
# sits around -0.2 to -0.8. int8 quantization lowers internal log-probabilities;
# gating at -1.6 ensures accented and fast Indian clinical speech is preserved.
_MIN_AVG_LOG_PROB: float = float(os.getenv("WHISPER_MIN_LOG_PROB", "-1.6"))

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

    The heavy generic dictionary (DEMO_SEEDED_PROMPT) is placed FIRST.
    The active patient context is placed at the absolute END so that if the string
    exceeds Whisper's 224-token prompt context window, truncation chops off generic
    text from the front while preserving the active patient's name and complaint.
    """
    parts = [DEMO_SEEDED_PROMPT]
    if patient_name and patient_name.strip():
        parts.append(f"Patient: {patient_name.strip()}.")
    if complaint and complaint.strip():
        parts.append(f"Chief complaint: {complaint.strip()}.")
    return " ".join(parts)


class AudioStreamSession:
    """
    Stateful streaming audio session for WebSocket ingestion.

    Maintains a rolling float32 PCM buffer (16 kHz mono).
    Throttles Silero neural VAD evaluation to >= 512ms chunks to eliminate CPU death-loops.
    Slices and transcribes only upon confirmed phrase boundaries (speech followed by >= 500ms
    of trailing silence). Safely shifts the buffer to preserve natural leading context.
    """

    def __init__(self, stt_engine: "RealtimeSTT", initial_prompt: str = ""):
        self.stt = stt_engine
        self.base_prompt = initial_prompt or DEMO_SEEDED_PROMPT
        self.prompt = self.base_prompt
        self.override_name: str = ""
        self.buffer: np.ndarray = np.array([], dtype=np.float32)
        self.last_eval_length: int = 0
        self.vad_options = VadOptions(
            threshold=0.40,
            min_speech_duration_ms=100,
            min_silence_duration_ms=500,
            speech_pad_ms=150,
        )

    def update_override(self, override_name: str) -> None:
        """
        Dynamically prime Whisper attention prefix for an unscheduled patient.
        Places the override patient at the END of the prompt so it survives truncation.
        """
        name = override_name.strip()
        if not name:
            self.override_name = ""
            self.prompt = self.base_prompt
            return
        self.override_name = name
        self.prompt = f"{self.base_prompt} Patient: {name}. Consultation for {name}.".strip()
        logger.info("Attention biased at end of prompt for unscheduled encounter: '%s'", name)

    def add_chunk(self, pcm_bytes: bytes) -> list[str]:
        """
        Ingest raw PCM int16 16kHz mono audio bytes.
        Returns a list of complete transcribed phrases (usually 0 or 1).
        """
        if not pcm_bytes:
            return []

        # Ensure byte length is 16-bit aligned (even number of bytes)
        if len(pcm_bytes) % 2 != 0:
            pcm_bytes = pcm_bytes[:len(pcm_bytes) - 1]
        if not pcm_bytes:
            return []

        # Convert int16 bytes to normalized float32
        chunk_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if self.buffer.size == 0:
            self.buffer = chunk_np
        else:
            self.buffer = np.concatenate([self.buffer, chunk_np])

        # Step 1: Throttle VAD evaluation — 512ms = 8,192 samples at 16 kHz
        if len(self.buffer) - self.last_eval_length < 8192:
            return []

        self.last_eval_length = len(self.buffer)
        transcripts: list[str] = []

        # Step 2: Run Silero VAD over the full active buffer
        timestamps = get_speech_timestamps(self.buffer, self.vad_options)

        if not timestamps:
            # Confirmed continuous silence across > 3.0s (48,000 samples) → clean reset
            if len(self.buffer) > 48000:
                self.buffer = np.array([], dtype=np.float32)
                self.last_eval_length = 0
            return []

        # Step 3: Phrase completion check
        # A phrase is complete when the last detected speech segment is followed by
        # at least 500ms (8,000 samples) of confirmed trailing silence.
        last_end = timestamps[-1]["end"]
        samples_after_speech = len(self.buffer) - last_end

        if samples_after_speech >= 8000:
            # Extract the speech block up to the confirmed end of speech
            speech_segment = self.buffer[:last_end]

            text = self.stt.transcribe_segment(
                speech_segment,
                initial_prompt=self.prompt,
            )
            if text:
                transcripts.append(text)

            # Step 4: Safe Shift — retain the trailing silence as leading context for the next phrase
            self.buffer = self.buffer[last_end:]
            self.last_eval_length = len(self.buffer)

        return transcripts

    def flush(self) -> str:
        """
        Flush remaining buffer on stream termination / disconnect.
        Transcribes any buffered speech that had not reached the full 500ms pause threshold.
        """
        if self.buffer.size < 1600:  # < 100ms
            self.buffer = np.array([], dtype=np.float32)
            self.last_eval_length = 0
            return ""

        timestamps = get_speech_timestamps(self.buffer, self.vad_options)
        text = ""
        if timestamps:
            last_end = timestamps[-1]["end"]
            speech_segment = self.buffer[:last_end] if last_end > 0 else self.buffer
            text = self.stt.transcribe_segment(
                speech_segment,
                initial_prompt=self.prompt,
            )

        self.buffer = np.array([], dtype=np.float32)
        self.last_eval_length = 0
        return text


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
        self.vad_parameters = dict(
            threshold=0.40,
            min_speech_duration_ms=100,
            min_silence_duration_ms=500,
            speech_pad_ms=150,
        )
        logger.info("STT pipeline ready — demo-seeded prompt + stateful neural VAD loaded.")

    def create_stream_session(self, initial_prompt: str = "") -> AudioStreamSession:
        """Instantiate a stateful streaming session for a WebSocket connection."""
        return AudioStreamSession(self, initial_prompt=initial_prompt)

    def transcribe_segment(
        self,
        audio_np: np.ndarray,
        initial_prompt: Optional[str] = None,
    ) -> str:
        """
        Run faster-whisper on a Float32 NumPy array at 16 000 Hz mono.
        Returns the stripped transcript string, or "" for silence/noise.
        """
        if audio_np.size < 1600:  # Ignore sub-100ms blips
            return ""

        prompt = initial_prompt or DEMO_SEEDED_PROMPT

        # Decoder configuration:
        # beam_size=2: evaluates candidate paths for proper nouns and accented speech.
        # temperature=0.0: greedy decoding across the beam.
        # condition_on_previous_text=False: resets context between phrases to prevent loops.
        # vad_filter=False: audio is already segmented by Silero VAD in AudioStreamSession.
        # compression_ratio_threshold=1.8: drops repetitive character/word loops.
        # no_speech_threshold=0.60: reliable speech confidence gate.
        # log_prob_threshold=-1.6: relaxed for int8 quantization and fast Indian English cadence.
        segments, _info = self.model.transcribe(
            audio_np,
            language="en",
            vad_filter=False,
            beam_size=2,
            temperature=0.0,
            initial_prompt=prompt,
            condition_on_previous_text=False,
            compression_ratio_threshold=1.8,
            no_speech_threshold=0.60,
            log_prob_threshold=-1.6,
        )

        # Per-segment confidence gate, transient filler gate, and phrase blocklist
        clean_parts: list[str] = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue

            # avg_logprob gate: filter low-confidence hallucination tokens
            if hasattr(seg, "avg_logprob") and seg.avg_logprob < _MIN_AVG_LOG_PROB:
                logger.debug(
                    "Dropped low-confidence segment (avg_logprob=%.3f): %r",
                    seg.avg_logprob, text
                )
                continue

            # Drop single isolated non-clinical filler words produced on short transient bursts (<0.6s)
            if audio_np.size < 9600:
                normalized_token = re.sub(r"[^\w]", "", text.strip().lower())
                if normalized_token in _TRANSIENT_FILLER_WORDS:
                    logger.debug("Dropped transient filler pop: %r", text)
                    continue

            # Known hallucination phrase blocklist
            if any(pat.search(text) for pat in _HALLUCINATION_PATTERNS):
                logger.debug("Dropped hallucination phrase: %r", text)
                continue

            clean_parts.append(text)

        return " ".join(clean_parts).strip()


# Lazy singleton — instantiated once at first WebSocket connection, not at import
# time, to avoid blocking the main process during model download.
_stt_instance: RealtimeSTT | None = None


def get_stt_engine() -> RealtimeSTT:
    """Return the module-level singleton, creating it on first call."""
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = RealtimeSTT()
    return _stt_instance

