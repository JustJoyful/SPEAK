"""
Realtime Speech-to-Text Pipeline

This module integrates faster-whisper with Native Silero VAD to provide
offline-first, zero-trust transcription via WebSocket streaming.
"""

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import get_vad_model, VadOptions, get_speech_timestamps
import logging

logger = logging.getLogger(__name__)

class RealtimeSTT:
    def __init__(self, model_size="tiny.en"):
        logger.info(f"Loading faster-whisper model ({model_size}) on CPU...")
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        logger.info("Loading Native Silero VAD...")
        self.vad_model = get_vad_model()
        self.vad_options = VadOptions()
        logger.info("STT pipeline initialized.")

    def transcribe_segment(self, audio_np: np.ndarray) -> str:
        """
        Runs faster-whisper on a Float32 NumPy array.
        Assumes 16000Hz mono audio.
        """
        if audio_np.size == 0:
            return ""
            
        segments, info = self.model.transcribe(audio_np, vad_filter=False, beam_size=1)
        text = " ".join([segment.text for segment in segments])
        return text.strip()

    def get_speech_timestamps(self, audio_np: np.ndarray):
        """
        Returns list of dicts with 'start' and 'end' frames of speech.
        """
        # The Silero VAD model requires batched/windowed processing which get_speech_timestamps handles
        return get_speech_timestamps(audio_np, self.vad_model, return_seconds=False)

stt_engine = RealtimeSTT()
