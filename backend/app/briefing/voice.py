import hashlib
import base64
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from time import monotonic
from urllib.parse import quote
import wave

import httpx
from sqlalchemy import select, text as sql_text
from sqlalchemy.exc import IntegrityError

from .accounting import observe
from .models import GeneratedAudio

RATE = 22050
STYLES = {
    "professional": (158, 48),
    "energetic": (182, 63),
    "casual": (150, 55),
    "cyberpunk": (146, 35),
    "jarvis": (154, 42),
}


def wav_bytes(pcm):
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        target.writeframes(pcm)
    return out.getvalue()


def convert_audio(content):
    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(RATE),
        "pipe:1",
    ]
    return subprocess.run(
        args, input=content, capture_output=True, check=True, timeout=45
    ).stdout


def local_pcm(text, lang, voice):
    speed, pitch = STYLES.get(voice, STYLES["professional"])
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if binary:
        result = subprocess.run(
            [
                binary,
                "--stdout",
                "-v",
                lang,
                "-s",
                str(speed),
                "-p",
                str(pitch),
                "--stdin",
            ],
            input=text.encode(),
            capture_output=True,
            timeout=40,
            check=True,
        )
        pcm = convert_audio(result.stdout)
    else:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.briefing.local_speech",
                lang,
                str(speed),
                str(pitch),
            ],
            input=text.encode(),
            capture_output=True,
            timeout=40,
            check=True,
        )
        pcm = result.stdout
    if len(pcm) < RATE // 10:
        raise RuntimeError("Offline speech produced no audible samples")
    return pcm


def provider_config(voice):
    kind = os.getenv("TTS_PROVIDER", "local")
    if kind in {"local", "mock"}:
        return "local", "espeak-ng", voice
    if kind != "elevenlabs":
        raise ValueError("Unknown speech provider")
    voice_id = json.loads(os.getenv("ELEVENLABS_VOICE_MAP") or "{}").get(
        voice
    ) or os.getenv("ELEVENLABS_VOICE_ID")
    if not voice_id or not os.getenv("ELEVENLABS_API_KEY"):
        raise ValueError("Configure a permitted ElevenLabs voice and API key")
    return kind, os.getenv("ELEVENLABS_MODEL") or "eleven_multilingual_v2", voice_id


def render_segment(db, text, lang, voice, config, reference_id):
    kind, model, voice_id = config
    start = monotonic()
    try:
        if kind == "local":
            return local_pcm(text, lang, voice)
        result = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{quote(voice_id, safe='')}",
            params={"output_format": "mp3_44100_128"},
            timeout=httpx.Timeout(60, connect=5),
            json={"text": text, "model_id": model},
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        )
        result.raise_for_status()
        pcm = convert_audio(result.content)
        if not pcm:
            raise ValueError("Speech provider returned empty audio")
        return pcm
    finally:
        observe(
            db,
            "tts",
            model,
            characters=len(text),
            seconds=monotonic() - start,
            reference_id=reference_id,
            measured_usd=0 if kind == "local" else None,
        )


def _bucket():
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(
            connect_timeout=4,
            read_timeout=30,
            retries={"max_attempts": 2},
            s3={"addressing_style": "path"},
        ),
    )
    return client, os.getenv("MINIO_BUCKET") or "sourcera-audio"


def _local_path(key):
    return Path(os.getenv("AUDIO_DIR") or ".data/audio") / key


def put_object(key, content):
    if os.getenv("AUDIO_STORAGE", "local") == "minio":
        client, bucket = _bucket()
        client.put_object(Bucket=bucket, Key=key, Body=content, ContentType="audio/wav")
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
            target.write(content)
        os.replace(target.name, path)


def read_object(key):
    if os.getenv("AUDIO_STORAGE", "local") == "minio":
        client, bucket = _bucket()
        body = client.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            return body.read()
        finally:
            body.close()
    return _local_path(key).read_bytes()


def render_audio(db, segments, voice, reference_id):
    config = provider_config(voice)
    try:
        return _render_audio(db, segments, voice, reference_id, config)
    except (httpx.HTTPError, subprocess.SubprocessError):
        if config[0] == "elevenlabs" and os.getenv("TTS_LOCAL_FALLBACK", "1") == "1":
            return _render_audio(
                db, segments, voice, reference_id, ("local", "espeak-ng", voice)
            )
        raise


def render_aligned(db, parts, config, reference_id):
    """Synthesize paragraph batches and retain provider character timings."""
    _, model, voice_id = config
    chunks = []
    current, size = [], 0
    for text, language in parts:
        if current and (size + len(text) + 2 > 8000 or language != current[0][1]):
            chunks.append(current)
            current, size = [], 0
        current.append((text, language))
        size += len(text) + 2
    if current:
        chunks.append(current)
    pcm, boundaries = bytearray(), []
    for chunk in chunks:
        joined = "\n\n".join(text for text, _ in chunk)
        start = monotonic()
        try:
            response = httpx.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{quote(voice_id, safe='')}/with-timestamps",
                params={"output_format": "mp3_44100_128"},
                timeout=httpx.Timeout(150, connect=5),
                json={"text": joined, "model_id": model},
                headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            )
            response.raise_for_status()
            result = response.json()
            alignment = result["alignment"]
            times = alignment["character_start_times_seconds"]
            if "".join(alignment["characters"]) != joined or len(times) != len(joined):
                raise ValueError("Speech alignment does not match the verified script")
            audio = convert_audio(
                base64.b64decode(result["audio_base64"], validate=True)
            )
            duration = len(audio) / (2 * RATE)
            if not audio or any(
                not math.isfinite(t) or t < 0 or t > duration for t in times
            ):
                raise ValueError("Speech returned invalid timing information")
            if times != sorted(times):
                raise ValueError("Speech timings are out of order")
            offset, position, starts = len(pcm) / (2 * RATE), 0, []
            for text, _ in chunk:
                starts.append(times[position])
                position += len(text) + 2
            starts[0] = 0
            for index, cue in enumerate(starts):
                end = starts[index + 1] if index + 1 < len(starts) else duration + 0.2
                boundaries.append([offset + cue, offset + end])
            pcm.extend(audio)
            pcm.extend(b"\0\0" * (RATE // 5))
        finally:
            observe(
                db,
                "tts",
                model,
                characters=len(joined),
                seconds=monotonic() - start,
                reference_id=reference_id,
            )
    return pcm, boundaries


def _render_audio(db, segments, voice, reference_id, config):
    parts = [(s.text, s.language) for s in segments]
    key = hashlib.sha256(
        json.dumps([2, config, voice, parts], ensure_ascii=False).encode()
    ).hexdigest()
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "speech-" + key},
        )
    existing = db.scalar(select(GeneratedAudio).where(GeneratedAudio.cache_key == key))
    if existing:
        return existing
    if (
        config[0] == "elevenlabs"
        and len(parts) > 1
        and os.getenv("ELEVENLABS_BATCH_TTS", "1") == "1"
    ):
        pcm, boundaries = render_aligned(db, parts, config, reference_id)
    else:
        pcm, boundaries = bytearray(), []
        for text, lang in parts:
            start = len(pcm) / (2 * RATE)
            pcm.extend(render_segment(db, text, lang, voice, config, reference_id))
            pcm.extend(b"\0\0" * (RATE // 5))
            boundaries.append([start, len(pcm) / (2 * RATE)])
    content = wav_bytes(pcm)
    digest = hashlib.sha256(content).hexdigest()
    audio = GeneratedAudio(
        cache_key=key,
        object_key=f"speech/{digest}.wav",
        boundaries=boundaries,
        provider=config[0],
        duration_seconds=boundaries[-1][1],
    )
    put_object(audio.object_key, content)
    try:
        with db.begin_nested():
            db.add(audio)
            db.flush()
    except IntegrityError:
        audio = db.scalars(
            select(GeneratedAudio).where(GeneratedAudio.cache_key == key)
        ).one()
    return audio


def transcribe(db, content, content_type, language, reference_id):
    provider = os.getenv("STT_PROVIDER", "mock")
    if provider == "mock":
        if content_type != "text/plain":
            raise ValueError(
                "Microphone transcription needs a configured Whisper endpoint. You can type your question."
            )
        return content.decode("utf8").strip()
    if provider not in {"whisper", "elevenlabs"}:
        raise ValueError("Unknown transcription provider")
    extensions = {
        "audio/mp4": "m4a",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/flac": "flac",
        "video/webm": "webm",
    }
    base_type = content_type.partition(";")[0]
    if base_type not in extensions:
        raise ValueError("Unsupported recording format")
    model = (
        (os.getenv("ELEVENLABS_STT_MODEL") or "scribe_v2")
        if provider == "elevenlabs"
        else (os.getenv("STT_MODEL") or "whisper-1")
    )
    start = monotonic()
    audio_minutes = 0
    if float(os.getenv("STT_USD_PER_MINUTE", "0")):
        audio_minutes = len(convert_audio(content)) / (2 * RATE * 60)
    try:
        if provider == "elevenlabs":
            url = "https://api.elevenlabs.io/v1/speech-to-text"
            headers = {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}
            data = {
                "model_id": model,
                "tag_audio_events": "false",
                "timestamps_granularity": "none",
            }
        else:
            url = (os.getenv("STT_BASE_URL") or "https://api.openai.com/v1").rstrip(
                "/"
            ) + "/audio/transcriptions"
            key = os.getenv("STT_API_KEY") or os.getenv("LLM_API_KEY")
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            data = {"language": language, "model": model}
        result = httpx.post(
            url,
            headers=headers,
            files={"file": (f"recording.{extensions[base_type]}", content, base_type)},
            data=data,
            timeout=httpx.Timeout(60, connect=5),
        )
        result.raise_for_status()
        return result.json()["text"].strip()
    finally:
        observe(
            db,
            "stt",
            model,
            seconds=monotonic() - start,
            reference_id=reference_id,
            estimated_usd=audio_minutes * float(os.getenv("STT_USD_PER_MINUTE", "0")),
        )
