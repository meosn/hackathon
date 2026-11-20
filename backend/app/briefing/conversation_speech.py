"""Authorize a single-use ElevenLabs TTS connection without exposing the API key."""

import json
import os

import httpx
from fastapi import HTTPException


def enabled():
    return os.getenv("REALTIME_SPEECH_PROVIDER", "openai") == "elevenlabs" and bool(
        os.getenv("ELEVENLABS_API_KEY")
    )


def session(voice_profile_id):
    if not enabled():
        raise HTTPException(503, "Streaming ElevenLabs speech is not configured")
    mapping = json.loads(os.getenv("ELEVENLABS_VOICE_MAP") or "{}")
    voice_id = mapping.get(voice_profile_id) or os.getenv("ELEVENLABS_VOICE_ID")
    if not voice_id:
        raise HTTPException(503, "This narrator has no configured ElevenLabs voice")
    try:
        result = httpx.post(
            "https://api.elevenlabs.io/v1/single-use-token/tts_websocket",
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            timeout=httpx.Timeout(10, connect=4),
        )
        result.raise_for_status()
        token = result.json()["token"]
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise ValueError("Invalid speech authorization")
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(
            503, "ElevenLabs speech could not connect. Please retry."
        ) from exc
    return {
        "token": token,
        "voice_id": voice_id,
        "voice_profile_id": voice_profile_id,
        "model_id": os.getenv("ELEVENLABS_CONVERSATION_MODEL") or "eleven_flash_v2_5",
        "sample_rate": 24000,
    }
