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
    DEMO_SEEDED_PROMPT,
    get_stt_engine,
    _HALLUCINATION_PATTERNS,
    _MIN_AVG_LOG_PROB,
    _RMS_FLOOR,
)


def test_build_clinical_prompt_defaults():
    """Verify prompt returns the weaponized demo-seeded prompt when no patient context is given."""
    prompt = build_clinical_prompt()
    # Must contain demo patient names
    assert "Rahul Sharma" in prompt
    assert "Meena Devi" in prompt
    assert "Ibrahim Sheikh" in prompt
    # Must contain demo drugs
    assert "pregabalin" in prompt
    assert "salbutamol" in prompt
    assert "atorvastatin" in prompt
    # The prompt must resolve to the full DEMO_SEEDED_PROMPT base
    assert prompt == DEMO_SEEDED_PROMPT


def test_build_clinical_prompt_dynamic_patient():
    """Verify dynamic prompt prepends patient name and chief complaint before the demo seed."""
    prompt = build_clinical_prompt(patient_name="Meena Devi", complaint="Follow-up, diabetes")
    assert prompt.startswith("Patient: Meena Devi. Chief complaint: Follow-up, diabetes.")
    # Demo seed terms must still be present
    assert "pregabalin" in prompt
    assert "metformin" in prompt


def test_vad_silence_detection():
    """Verify that pure silence (dead air) returns has_speech = False."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    silence = np.zeros(16000, dtype=np.float32)
    assert stt.has_speech(silence) is False
    assert stt.has_speech(np.array([], dtype=np.float32)) is False


def test_transcribe_empty_segment():
    """Verify that empty array returns empty transcript immediately."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    result = stt.transcribe_segment(np.array([], dtype=np.float32))
    assert result == ""


@pytest.mark.asyncio
async def test_async_worker_offload():
    """Verify that VAD and transcription execute in worker thread without blocking asyncio loop."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    silence = np.zeros(16000, dtype=np.float32)

    has_voice = await asyncio.to_thread(stt.has_speech, silence)
    assert has_voice is False

    custom_prompt = build_clinical_prompt("Rahul Sharma", "Fever, 3 days")
    with patch.object(stt.model, "transcribe") as mock_transcribe:
        mock_segment = MagicMock()
        mock_segment.text = "Patient Rahul Sharma presents with fever and chills."
        mock_segment.avg_logprob = -0.3  # high confidence
        mock_transcribe.return_value = ([mock_segment], None)

        fake_audio = np.random.randn(16000).astype(np.float32) * 0.1
        text = await asyncio.to_thread(stt.transcribe_segment, fake_audio, custom_prompt)

        assert "Rahul Sharma" in text
        mock_transcribe.assert_called_once()
        _, kwargs = mock_transcribe.call_args
        assert kwargs["initial_prompt"] == custom_prompt
        assert kwargs["condition_on_previous_text"] is False
        # Verify balanced (not over-aggressive) hallucination thresholds
        assert kwargs["no_speech_threshold"] == 0.65
        assert kwargs["compression_ratio_threshold"] == 1.9
        assert kwargs["temperature"] == 0.0   # scalar, not a list


def test_rms_floor_blocks_low_energy_noise():
    """Layer 1: Low-energy noise (AC hum, fan) must not reach the transcriber."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    # Generate audio at RMS=0.004 — below the 0.008 floor
    noise = np.random.randn(16000).astype(np.float32) * 0.004
    # Normalize to exact RMS=0.004
    noise = noise / (np.sqrt(np.mean(noise ** 2)) + 1e-9) * 0.004
    assert stt.has_speech(noise) is False, "Sub-floor noise must not be classified as speech"


def test_rms_floor_passes_real_speech():
    """Layer 1: Audio above the RMS floor must pass through."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    speech_like = np.random.randn(16000).astype(np.float32) * 0.05  # RMS ~0.05
    assert stt.has_speech(speech_like) is True


def test_hallucination_blocklist_catches_thanks():
    """Layer 4: 'Thank you.' / 'Thanks.' / 'Thank you very much.' must be caught."""
    phrases = [
        "Thank you.", "Thanks.", "Thank you!", "Thanks,",
        "Thank you very much.", "Thank you very much!", "thank you very much",
    ]
    for phrase in phrases:
        matched = any(pat.search(phrase) for pat in _HALLUCINATION_PATTERNS)
        assert matched, f"Hallucination blocklist missed: {phrase!r}"


def test_hallucination_blocklist_catches_noise_artifacts():
    """Layer 4: Whisper noise artifacts like '...', '[Music]', repetition."""
    artifacts = ["...", "\u2026", "[Music]", "[Applause]", "aaaaaaaaaa", "subtitles by AI"]
    for artifact in artifacts:
        matched = any(pat.search(artifact) for pat in _HALLUCINATION_PATTERNS)
        assert matched, f"Hallucination blocklist missed: {artifact!r}"


def test_hallucination_blocklist_passes_real_speech():
    """Layer 4: Legitimate clinical speech must NOT be blocked."""
    clinical = [
        "Patient presents with fever for 3 days.",
        "BP 120 over 80, SpO2 98 percent.",
        "Prescribed Dolo 650 twice daily.",
        "Chief complaint is abdominal pain.",
    ]
    for phrase in clinical:
        matched = any(pat.search(phrase) for pat in _HALLUCINATION_PATTERNS)
        assert not matched, f"Hallucination blocklist incorrectly blocked: {phrase!r}"


def test_low_confidence_segment_dropped():
    """Layer 3: Segments with avg_logprob below threshold must be filtered out."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")

    with patch.object(stt.model, "transcribe") as mock_transcribe:
        # One garbage segment (low log-prob), one real segment
        bad_seg = MagicMock()
        bad_seg.text = "Thanks for watching!"
        bad_seg.avg_logprob = -3.5  # garbage-level confidence

        good_seg = MagicMock()
        good_seg.text = "Prescription: Paracetamol 500mg."
        good_seg.avg_logprob = -0.4  # solid confidence

        mock_transcribe.return_value = ([bad_seg, good_seg], None)

        loud_audio = np.random.randn(16000).astype(np.float32) * 0.1
        result = stt.transcribe_segment(loud_audio)

        # Bad segment must be dropped, good segment must survive
        assert "Thanks for watching" not in result
        assert "Paracetamol" in result
