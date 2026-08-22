"""
Realtime Speech-to-Text Pipeline

Integrates faster-whisper with Native Silero VAD for offline-first,
zero-trust transcription via WebSocket streaming.

Design choices:
  - Audio is processed entirely in-memory as NumPy float32 arrays (no disk I/O).
  - The AudioContext on the frontend is forced to 16 kHz to avoid pitch distortion.
  - VAD gates Whisper to reduce hallucinations on silence.
"""

import logging
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps

logger = logging.getLogger(__name__)

_MODEL_SIZE = "tiny.en"


class RealtimeSTT:
    def __init__(self, model_size: str = _MODEL_SIZE):
        logger.info("Loading faster-whisper model (%s) on CPU …", model_size)
        # int8 quantisation keeps RAM low on edge hardware
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        # VadOptions defaults are sensible for medical speech at 16 kHz
        self.vad_options = VadOptions()
        logger.info("STT pipeline ready.")

    def transcribe_segment(self, audio_np: np.ndarray) -> str:
        """
        Run faster-whisper on a Float32 NumPy array at 16 000 Hz mono.
        Returns the stripped transcript string, or "" for silence/noise.
        """
        if audio_np.size == 0:
            return ""
        segments, _info = self.model.transcribe(
            audio_np,
            vad_filter=False,   # We apply VAD ourselves before calling this
            beam_size=1,        # Greedy — fastest for real-time use
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
