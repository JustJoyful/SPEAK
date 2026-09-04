"""Unit tests for Indian-accent optimized faster-whisper STT pipeline."""

import pytest
import asyncio
import numpy as np
from unittest.mock import patch, MagicMock

from backend.pipeline.stt import (
    RealtimeSTT,
    AudioStreamSession,
    build_clinical_prompt,
    DEFAULT_INDIAN_CLINICAL_PROMPT,
    DEMO_SEEDED_PROMPT,
    get_stt_engine,
    _HALLUCINATION_PATTERNS,
    _MIN_AVG_LOG_PROB,
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
    """Verify dynamic prompt appends patient name and chief complaint after the demo seed to survive truncation."""
    prompt = build_clinical_prompt(patient_name="Meena Devi", complaint="Follow-up, diabetes")
    assert prompt.endswith("Patient: Meena Devi. Chief complaint: Follow-up, diabetes.")
    # Demo seed terms must still be present
    assert "pregabalin" in prompt
    assert "metformin" in prompt


def test_transcribe_empty_segment():
    """Verify that sub-100ms or empty array returns empty transcript immediately."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    result = stt.transcribe_segment(np.array([], dtype=np.float32))
    assert result == ""
    # 50ms at 16kHz = 800 samples — must be dropped
    short_audio = np.random.randn(800).astype(np.float32)
    assert stt.transcribe_segment(short_audio) == ""


@pytest.mark.asyncio
async def test_async_worker_offload():
    """Verify that transcription executes with beam_size=1 and compression_ratio_threshold=1.8."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")

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
        assert kwargs["condition_on_previous_text"] is True
        assert kwargs["beam_size"] == 2
        assert kwargs["vad_filter"] is True
        assert kwargs["vad_parameters"] == stt.vad_parameters
        assert kwargs["no_speech_threshold"] == 0.6
        assert kwargs["log_prob_threshold"] == -2.0
        assert kwargs["compression_ratio_threshold"] == 1.8
        assert kwargs["temperature"] == 0.0   # scalar, not a list


def test_warmup_drop_hardware_mic_pops():
    """Verify that AudioStreamSession drops the first 400ms (6400 samples) to absorb hardware mic switch clicks/pops."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    session = stt.create_stream_session()

    # 200ms chunk (3200 samples) -> absorbed by warmup
    audio_200ms = (np.random.randn(3200).astype(np.float32) * 0.1 * 32768).astype(np.int16).tobytes()
    res1 = session.add_chunk(audio_200ms)
    assert res1 == []
    assert len(session.buffer) == 0
    assert session.warmup_samples_remaining == 3200

    # Another 300ms chunk (4800 samples) -> 3200 samples complete the warmup drop, 1600 samples enter buffer
    audio_300ms = (np.random.randn(4800).astype(np.float32) * 0.1 * 32768).astype(np.int16).tobytes()
    res2 = session.add_chunk(audio_300ms)
    assert res2 == []
    assert session.warmup_samples_remaining == 0
    assert len(session.buffer) == 1600


def test_transient_filler_words_dropped_on_short_burst():
    """Verify that isolated filler words like 'so', 'okay', 'yeah' are dropped when audio < 0.6s."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")

    with patch.object(stt.model, "transcribe") as mock_transcribe:
        for filler in ["so", "Okay.", "Yeah", "Thanks!", "um", "ah", "ok"]:
            mock_seg = MagicMock()
            mock_seg.text = filler
            mock_seg.avg_logprob = -0.5
            mock_transcribe.return_value = ([mock_seg], None)

            # Short burst: 0.4s (6400 samples < 9600)
            short_audio = np.random.randn(6400).astype(np.float32) * 0.05
            result = stt.transcribe_segment(short_audio)
            assert result == "", f"Transient filler {filler!r} should have been dropped on short burst"


def test_clinical_single_words_preserved_on_short_burst():
    """Verify that legitimate single-word clinical findings are NOT dropped."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")

    with patch.object(stt.model, "transcribe") as mock_transcribe:
        for clinical_word in ["Cough.", "Clear.", "Left.", "Normal.", "Nil.", "Pain."]:
            mock_seg = MagicMock()
            mock_seg.text = clinical_word
            mock_seg.avg_logprob = -0.3
            mock_transcribe.return_value = ([mock_seg], None)

            # Short burst: 0.4s (6400 samples)
            short_audio = np.random.randn(6400).astype(np.float32) * 0.05
            result = stt.transcribe_segment(short_audio)
            assert clinical_word in result, f"Clinical word {clinical_word!r} must be preserved"


def test_repeated_medical_words_preserved():
    """Verify that repeated medical dosage words are preserved intact."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")

    with patch.object(stt.model, "transcribe") as mock_transcribe:
        mock_seg = MagicMock()
        mock_seg.text = "Take two two-milligram pills daily."
        mock_seg.avg_logprob = -0.3
        mock_transcribe.return_value = ([mock_seg], None)

        audio = np.random.randn(16000 * 2).astype(np.float32) * 0.05
        result = stt.transcribe_segment(audio)
        assert "two two-milligram" in result



def test_audio_stream_session_throttling():
    """Verify that AudioStreamSession accumulates chunks and throttles VAD until >= 512ms (8192 samples)."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    session = stt.create_stream_session("Test prompt")
    session.warmup_samples_remaining = 0  # Test post-warmup VAD evaluation logic

    # Send 100ms chunk (1600 samples = 3200 bytes int16)
    chunk_100ms = (np.random.randn(1600).astype(np.float32) * 0.05 * 32768).astype(np.int16).tobytes()

    with patch("backend.pipeline.stt.get_speech_timestamps") as mock_vad:
        # First 100ms: below 512ms threshold -> no VAD call
        res = session.add_chunk(chunk_100ms)
        assert res == []
        mock_vad.assert_not_called()

        # Send 4 more 100ms chunks (total 500ms -> 8000 samples, still < 8192)
        for _ in range(4):
            session.add_chunk(chunk_100ms)
        mock_vad.assert_not_called()

        # 6th chunk brings total to 600ms (9600 samples >= 8192) -> VAD must be called
        mock_vad.return_value = []
        res = session.add_chunk(chunk_100ms)
        assert res == []
        mock_vad.assert_called_once()


def test_audio_stream_session_phrase_completion_and_shift():
    """Verify that speech followed by >= 500ms trailing silence emits transcript and shifts buffer."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    session = stt.create_stream_session("Test prompt")
    session.warmup_samples_remaining = 0  # Test post-warmup phrase boundary shift

    # Construct 1.5s speech + 0.6s trailing silence = 2.1s (33600 samples)
    total_samples = int(2.1 * 16000)
    pcm_bytes = (np.random.randn(total_samples).astype(np.float32) * 0.05 * 32768).astype(np.int16).tobytes()

    speech_end = int(1.5 * 16000)  # speech ended at 1.5s, trailing silence is 0.6s (9600 samples >= 8000)

    with patch("backend.pipeline.stt.get_speech_timestamps") as mock_vad, \
         patch.object(stt, "transcribe_segment") as mock_transcribe:
        mock_vad.return_value = [{"start": 1600, "end": speech_end}]
        mock_transcribe.return_value = "Patient Rahul Sharma 34 male"

        transcripts = session.add_chunk(pcm_bytes)

        assert transcripts == ["Patient Rahul Sharma 34 male"]
        mock_transcribe.assert_called_once()
        # Verify buffer was shifted past speech_end
        assert len(session.buffer) == total_samples - speech_end


def test_audio_stream_session_silence_reset():
    """Verify that > 3.0s (48000 samples) of confirmed silence resets the buffer to empty."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    session = stt.create_stream_session()
    session.warmup_samples_remaining = 0  # Test post-warmup silence timeout

    # 3.2s of silence (51200 samples)
    silence_bytes = (np.zeros(51200, dtype=np.int16)).tobytes()

    with patch("backend.pipeline.stt.get_speech_timestamps", return_value=[]):
        res = session.add_chunk(silence_bytes)
        assert res == []
        assert len(session.buffer) == 0
        assert session.last_eval_length == 0



def test_audio_stream_session_flush():
    """Verify flush transcribes any remaining speech in buffer and cleans up."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    session = stt.create_stream_session("Test prompt")

    # Ingest 1.0s audio without trailing silence
    pcm_bytes = (np.random.randn(16000).astype(np.float32) * 0.05 * 32768).astype(np.int16).tobytes()
    session.buffer = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    with patch("backend.pipeline.stt.get_speech_timestamps") as mock_vad, \
         patch.object(stt, "transcribe_segment") as mock_transcribe:
        mock_vad.return_value = [{"start": 1000, "end": 15000}]
        mock_transcribe.return_value = "Final consultation note"

        text = session.flush()
        assert text == "Final consultation note"
        assert len(session.buffer) == 0


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


def test_add_chunk_odd_bytes_no_crash():
    """Verify that odd-length byte buffers are truncated safely without raising ValueError."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    session = AudioStreamSession(stt)
    # Send 1 byte
    res1 = session.add_chunk(b"\x00")
    assert res1 == []
    # Send odd number of bytes (e.g. 5 bytes)
    res2 = session.add_chunk(b"\x00\x01\x00\x02\x03")
    assert res2 == []
    # Send empty bytes
    assert session.add_chunk(b"") == []


def test_audio_stream_session_update_override():
    """Verify update_override appends patient attention bias to the end of prompt."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    session = AudioStreamSession(stt)
    assert session.override_name == ""

    session.update_override("Venkatraman")
    assert session.override_name == "Venkatraman"
    assert session.prompt.endswith("Patient: Venkatraman. Consultation for Venkatraman.")


def test_transcribe_segment_uses_beam2_and_context():
    """Verify that transcribe_segment uses beam_size=2, condition_on_previous_text=True, and vad_filter=True."""
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    with patch.object(stt.model, "transcribe") as mock_transcribe:
        mock_seg = MagicMock()
        mock_seg.text = "Patient Rahul Sharma reports fever."
        mock_seg.avg_logprob = -0.3
        mock_transcribe.return_value = ([mock_seg], None)

        audio = np.random.randn(16000).astype(np.float32) * 0.1
        res = stt.transcribe_segment(audio, initial_prompt="Test Prompt")

        assert "Rahul Sharma" in res
        mock_transcribe.assert_called_once()
        _, kwargs = mock_transcribe.call_args
        assert kwargs.get("beam_size") == 2
        assert kwargs.get("condition_on_previous_text") is True
        assert kwargs.get("log_prob_threshold") == -2.0
        assert kwargs.get("vad_filter") is True
        assert kwargs.get("vad_parameters") == stt.vad_parameters
        assert kwargs.get("temperature") == 0.0
        assert "hotwords" not in kwargs


def test_build_clinical_prompt_preserves_active_patient_in_224_tokens():
    """Verify active patient is placed at the end so it survives Whisper 224-token prompt truncation."""
    prompt = build_clinical_prompt("Rahul Sharma", "fever three days")
    stt = RealtimeSTT(model_size="tiny.en", compute_type="int8")
    enc = stt.model.hf_tokenizer.encode(prompt)
    retained_text = stt.model.hf_tokenizer.decode(enc.ids[-224:])
    assert "Rahul Sharma" in retained_text



