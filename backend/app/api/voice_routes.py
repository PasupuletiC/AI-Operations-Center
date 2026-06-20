"""
Voice Incident Reporter — accepts audio from browser microphone,
transcribes it using Groq's Whisper API, and returns the text
so the frontend can populate the email processing textarea.

Endpoint: POST /api/voice/transcribe
  - Accepts: multipart/form-data with 'audio' file field
  - Returns: { "text": "transcribed text here" }
"""
import os
import logging
import httpx
from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import Dict, Any

logger = logging.getLogger(__name__)
router = APIRouter()

GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


@router.post("/voice/transcribe")
async def transcribe_voice(audio: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Transcribe a voice recording using Groq's Whisper API.

    The frontend sends audio as WebM/OGG (from MediaRecorder).
    Returns the transcribed text ready to feed into the pipeline.
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY not configured.")

    audio_bytes = await audio.read()
    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio file is too small.")

    # Determine filename — Groq Whisper needs a supported extension
    filename    = audio.filename or "recording.webm"
    content_type = audio.content_type or "audio/webm"

    logger.info(f"[Voice] Transcribing {len(audio_bytes)} bytes — {filename}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                GROQ_WHISPER_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={
                    "file": (filename, audio_bytes, content_type),
                },
                data={
                    "model":    "whisper-large-v3",
                    "language": "en",
                },
            )

        if response.status_code != 200:
            detail = response.text[:200]
            logger.warning(f"[Voice] Whisper API error: {response.status_code} — {detail}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Whisper API error: {detail}"
            )

        data = response.json()
        text = data.get("text", "").strip()

        if not text:
            raise HTTPException(
                status_code=422,
                detail="No speech detected in the audio."
            )

        logger.info(f"[Voice] ✅ Transcribed: '{text[:80]}...' " if len(text) > 80 else
                    f"[Voice] ✅ Transcribed: '{text}'")
        return {"text": text, "duration_chars": len(text)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Voice] Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")
