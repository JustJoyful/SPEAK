"""Unit tests for Indian-accent optimized faster-whisper STT pipeline."""

import os
import pytest
import asyncio
import numpy as np
from unittest.mock import patch, MagicMock

from backend.pipeline.stt import (
    RealtimeSTT,
    build_clinical_prompt,
    DEFAULT_INDIAN_CLINICAL_PROMPT,
    get_stt_engine
)


def test_build_clinical_prompt_defaults():
    """Verify prompt returns rich Indian medical default prompt when no patient context is given."""
    prompt = build_clinical_prompt()
    assert "Dolo 650" in prompt
    assert "Paracetamol" in prompt
    assert "9876543210" in prompt
    assert "Aadhaar" in prompt
    assert prompt == DEFAULT_INDIAN_CLINICAL_PROMPT


def test_build_clinical_prompt_dynamic_patient():
    """Verify dynamic prompt prepends patient name and chief complaint."""
    prompt = build_clinical_prompt(patient_name="Meena Devi", complaint="Follow-up, diabetes")
    assert prompt.startswith("Patient: Meena Devi. Chief Complaint: Follow-up, diabetes.")
    assert "Dolo 650" in prompt
    assert "Metformin" in prompt


def test_vad_silence_detection():
    """Verify that pure silence (dead air) returns has_speech = False."""
    stt = RealtimeSTT(model_size="tiny.en") # Use tiny.en for fast test instantiation
    silence = np.zeros(16000, dtype=np.float32)
    assert stt.has_speech(silence) is False
    assert stt.has_speech(np.array([], dtype=np.float32)) is False


def test_transcribe_empty_segment():
    """Verify that empty array returns empty transcript immediately."""
    stt = RealtimeSTT(model_size="tiny.en")
    result = stt.transcribe_segment(np.array([], dtype=np.float32))
    assert result == ""


@pytest.mark.asyncio
async def test_async_worker_offload():
    """Verify that VAD and transcription execute in worker thread without blocking asyncio loop."""
    stt = RealtimeSTT(model_size="tiny.en")
    silence = np.zeros(16000, dtype=np.float32)

    has_voice = await asyncio.to_thread(stt.has_speech, silence)
    assert has_voice is False

    custom_prompt = build_clinical_prompt("Rahul Sharma", "Fever, 3 days")
    with patch.object(stt.model, "transcribe") as mock_transcribe:
        mock_segment = MagicMock()
        mock_segment.text = "Patient Rahul Sharma presents with fever and chills."
        mock_transcribe.return_value = ([mock_segment], None)

        fake_audio = np.random.randn(16000).astype(np.float32) * 0.1
        text = await asyncio.to_thread(stt.transcribe_segment, fake_audio, custom_prompt)

        assert "Rahul Sharma" in text
        mock_transcribe.assert_called_once()
        # Verify initial_prompt was passed to model
        _, kwargs = mock_transcribe.call_args
        assert kwargs["initial_prompt"] == custom_prompt
        assert kwargs["condition_on_previous_text"] is False
