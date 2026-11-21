"""Validate a consented voice sample and register it with ElevenLabs."""

import io
import re
import subprocess
import tempfile
import wave

import httpx
from fastapi import HTTPException

MAX_UPLOAD = 25 * 1024 * 1024
SAMPLE_RATE = 24_000
BYTES_PER_SECOND = SAMPLE_RATE * 2


def checked_sample(upload):
    data = upload.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Choose an audio file smaller than 25 MB.")
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
                    "120",
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
    if len(pcm) < 10 * BYTES_PER_SECOND:
        raise HTTPException(
            422, "Choose a recording with at least 10 seconds of speech."
        )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)
    return buffer.getvalue()


def clone_voice(api_key: str, sample: bytes, name="Custom") -> str:
    try:
        response = httpx.post(
            "https://api.elevenlabs.io/v1/voices/add",
            headers={"xi-api-key": api_key},
            data={"name": "Sourcera · " + name[:80]},
            files={"files": ("voice-sample.wav", sample, "audio/wav")},
            timeout=httpx.Timeout(90, connect=8),
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
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {400, 422}:
            raise HTTPException(
                422,
                "The recording could not be used. Choose a clear recording with one speaker and try again.",
            ) from exc
        if exc.response.status_code in {402, 403, 429}:
            raise HTTPException(
                503,
                "Voice creation is temporarily unavailable for this account. Your recording is kept so you can retry.",
            ) from exc
        raise HTTPException(
            502,
            "The voice service could not finish. Your recording is kept; please retry.",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            502, "ElevenLabs could not create the custom voice."
        ) from exc
    raise HTTPException(502, "ElevenLabs did not return a voice ID.")
