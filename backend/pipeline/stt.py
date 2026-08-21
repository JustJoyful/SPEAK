"""
Speech-to-Text Pipeline (Stub)

For the initial prototype and hackathon presentation, the actual STT processing 
is performed using the browser's Web Speech API on the frontend, and the partial 
transcripts are sent to the backend via POST /encounter/{token}/transcript.

This module is reserved for future integration with a real streaming STT model 
(e.g., Whisper, Deepgram) over WebSockets.
"""

async def process_audio_chunk(audio_bytes: bytes) -> str:
    """Mock function for processing raw audio chunks into text."""
    # In a real implementation, this would yield text from a speech recognition model
    return ""
