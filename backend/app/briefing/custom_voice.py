"""Validate a consented voice sample and register it with ElevenLabs."""

import io
import re
import subprocess
import tempfile
import wave

import httpx
from fastapi import HTTPException

MAX_UPLOAD = 10 * 1024 * 1024
SAMPLE_RATE = 24_000
BYTES_PER_SECOND = SAMPLE_RATE * 2


def checked_sample(upload):
    data = upload.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The sample must be 10 MiB or smaller.")
    try:
        with tempfile.TemporaryFile() as media:
            media.write(data)
            media.seek(0)
            decoded = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-protocol_whitelist",
                    "pipe,file",
                    "-format_whitelist",
                    "wav,mp3,flac,ogg,aac,mov,matroska,webm",
                    "-i",
                    "/dev/stdin",
                    "-map",
                    "0:a:0",
                    "-t",
                    "61",
                    "-ac",
                    "1",
                    "-ar",
                    str(SAMPLE_RATE),
                    "-f",
                    "s16le",
                    "pipe:1",
                ],
                stdin=media,
                capture_output=True,
                timeout=15,
            )
    except FileNotFoundError as exc:
        raise HTTPException(503, "Audio validation is unavailable.") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(422, "The audio sample could not be decoded.") from exc
    pcm = decoded.stdout
    if decoded.returncode or not pcm:
        raise HTTPException(422, "Choose a valid audio file.")
    if not 30 * BYTES_PER_SECOND <= len(pcm) <= 60 * BYTES_PER_SECOND:
        raise HTTPException(422, "The audio sample must be between 30 and 60 seconds.")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    return buffer.getvalue()


def clone_voice(api_key: str, sample: bytes) -> str:
    try:
        response = httpx.post(
            "https://api.elevenlabs.io/v1/voices/add",
            headers={"xi-api-key": api_key},
            data={"name": "Sourcera Custom"},
            files={"files": ("voice-sample.wav", sample, "audio/wav")},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        voice_id = payload.get("voice_id") if isinstance(payload, dict) else None
        if isinstance(voice_id, str) and re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", voice_id
        ):
            if payload.get("requires_verification") is not True:
                return voice_id
            raise HTTPException(
                422, "The sample requires verification in ElevenLabs before use."
            )
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            502, "ElevenLabs could not create the custom voice."
        ) from exc
    raise HTTPException(502, "ElevenLabs did not return a voice ID.")
