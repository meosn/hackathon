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
from array import array

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
    "gangsta": (146, 43),
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


def provider_config(voice, db=None):
    kind = os.getenv("TTS_PROVIDER", "local")
    if kind in {"local", "mock"}:
        return "local", "espeak-ng", voice
    if kind != "elevenlabs":
        raise ValueError("Unknown speech provider")
    voice_id = json.loads(os.getenv("ELEVENLABS_VOICE_MAP") or "{}").get(
        voice
    ) or os.getenv("ELEVENLABS_VOICE_ID")
    if db is not None:
        from app.accounts import VoiceProfile

        voice_id = (
            db.scalar(
                select(VoiceProfile.elevenlabs_voice_id).where(
                    VoiceProfile.slug == voice
                )
            )
            or voice_id
        )
    if not voice_id or not os.getenv("ELEVENLABS_API_KEY"):
        raise ValueError("Configure a permitted ElevenLabs voice and API key")
    return kind, os.getenv("ELEVENLABS_MODEL") or "eleven_multilingual_v2", voice_id


def render_segment(db, text, lang, voice, config, reference_id):
    kind, model, voice_id = config
    start = monotonic()
    try:
        if kind == "local":
            return local_pcm(text, lang, voice)
        if kind == "openai":
            result = httpx.post(
                "https://api.openai.com/v1/audio/speech",
                timeout=httpx.Timeout(30, connect=5),
                json={
                    "model": model,
                    "voice": voice_id,
                    "input": text,
                    "response_format": "mp3",
                },
                headers={
                    "Authorization": "Bearer "
                    + (os.getenv("OPENAI_API_KEY") or os.environ["LLM_API_KEY"])
                },
            )
            result.raise_for_status()
            pcm = convert_audio(result.content)
            if not pcm:
                raise ValueError("Speech provider returned empty audio")
            return pcm
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


def render_audio(db, segments, voice, reference_id, config=None):
    config = config or provider_config(voice, db)
    try:
        return _render_audio(db, segments, voice, reference_id, config)
    except (httpx.HTTPError, subprocess.SubprocessError):
        if config[0] == "elevenlabs" and os.getenv("TTS_LOCAL_FALLBACK", "1") == "1":
            return _render_audio(
                db, segments, voice, reference_id, ("local", "espeak-ng", voice)
            )
        raise


def render_aligned(db, parts, config, reference_id, pauses=None):
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
    part_offset = 0
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
            offset, position, starts, positions = len(pcm) / (2 * RATE), 0, [], []
            for text, _ in chunk:
                starts.append(times[position])
                positions.append(position)
                position += len(text) + 2
            starts[0] = 0
            # Preserve the original verified text/alignment while adding only the
            # missing breathing space between sentences and story paragraphs.
            ends = alignment.get("character_end_times_seconds") or []
            inserts = []
            added = 0.0
            for index in range(1, len(starts)):
                target = pauses[part_offset + index - 1] if pauses else 0.32
                previous = positions[index] - 3
                while previous > 0 and not joined[previous].isalnum():
                    previous -= 1
                end = ends[previous] if len(ends) == len(joined) else starts[index]
                if not math.isfinite(end) or not 0 <= end <= starts[index]:
                    end = starts[index]
                gap = max(0, target - (starts[index] - end))
                gap_frames = round(gap * RATE)
                cut = round((end + starts[index]) / 2 * RATE) * 2
                inserts.append((cut, gap_frames))
                added += gap_frames / RATE
                starts[index] += added
            if inserts:
                samples = bytearray(audio)
                fade = round(RATE * 0.002)
                for cut, frames in inserts:
                    if not frames:
                        continue
                    for frame in range(fade):
                        for pos, gain in (
                            (cut - (frame + 1) * 2, (frame + 1) / fade),
                            (cut + frame * 2, frame / fade),
                        ):
                            if 0 <= pos < len(samples) - 1:
                                value = int.from_bytes(
                                    samples[pos : pos + 2], "little", signed=True
                                )
                                samples[pos : pos + 2] = int(value * gain).to_bytes(
                                    2, "little", signed=True
                                )
                audio = bytes(samples)
                paced, cursor = bytearray(), 0
                for cut, frames in inserts:
                    paced.extend(audio[cursor:cut])
                    paced.extend(b"\0\0" * frames)
                    cursor = cut
                paced.extend(audio[cursor:])
                audio = bytes(paced)
                duration = len(audio) / (2 * RATE)
            for index, cue in enumerate(starts):
                end = starts[index + 1] if index + 1 < len(starts) else duration + 0.2
                boundaries.append([offset + cue, offset + end])
            pcm.extend(audio)
            pcm.extend(b"\0\0" * (RATE // 5))
            part_offset += len(chunk)
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


def trim_long_pauses(pcm, boundaries):
    """Shorten sustained quiet only, keeping words and their shifted cues intact."""
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    window = round(RATE * 0.01)
    runs, start = [], None
    for pos in range(0, len(samples), window):
        frame = samples[pos : pos + window]
        quiet = sum(value * value for value in frame) / len(frame) < 200**2
        if quiet and start is None:
            start = pos
        if not quiet and start is not None:
            runs.append((start, pos))
            start = None
    if start is not None:
        runs.append((start, len(samples)))
    keep = round(RATE * 0.16)
    cuts = [
        (left + keep // 2, right - (keep - keep // 2))
        for left, right in runs
        if right - left > RATE * 0.22
    ]
    if not cuts:
        return pcm, boundaries
    output, cursor = bytearray(), 0
    for left, right in cuts:
        output.extend(pcm[cursor * 2 : left * 2])
        cursor = right
    output.extend(pcm[cursor * 2 :])

    def shifted(seconds):
        frame = round(seconds * RATE)
        removed = sum(max(0, min(frame, right) - left) for left, right in cuts)
        return (frame - removed) / RATE

    return bytes(output), [[shifted(start), shifted(end)] for start, end in boundaries]


def retime_trump_cache(db, audio):
    """Shorten an existing recording without another provider call or lost words."""
    from .models import Briefing, BriefingSegment

    editions = db.scalars(
        select(Briefing).where(Briefing.audio_id == audio.id).order_by(Briefing.id).with_for_update()
    ).all()
    rows = []
    for edition in editions:
        if edition.voice_profile_id != "energetic":
            raise ValueError("Only Trump recordings can be retimed")
        segments = db.scalars(
            select(BriefingSegment).where(BriefingSegment.briefing_id == edition.id)
            .order_by(BriefingSegment.position)
        ).all()
        if len(segments) != len(audio.boundaries):
            raise ValueError("Cached audio and transcript boundaries do not match")
        rows.append((edition, segments))
    with wave.open(io.BytesIO(read_object(audio.object_key)), "rb") as recording:
        if (recording.getnchannels(), recording.getsampwidth(), recording.getframerate()) != (1, 2, RATE):
            raise ValueError("Unsupported cached recording format")
        original = recording.readframes(recording.getnframes())
    pcm, cues = trim_long_pauses(original, audio.boundaries)
    if pcm == original:
        return audio
    content = wav_bytes(pcm)
    key = "speech/" + hashlib.sha256(content).hexdigest() + ".wav"
    put_object(key, content)
    audio.object_key, audio.boundaries = key, cues
    audio.duration_seconds = len(pcm) / (2 * RATE)
    for edition, segments in rows:
        edition.duration_seconds = audio.duration_seconds
        for segment, (start, end) in zip(segments, cues, strict=True):
            segment.start_seconds, segment.end_seconds = start, end
    db.flush()
    return audio


def _render_audio(db, segments, voice, reference_id, config, *, segment_pause=None):
    parts = [(s.text, s.language) for s in segments]
    compact_pauses = voice == "energetic" and segment_pause is None
    recipe = [5 if compact_pauses else 3, config, voice, parts]
    if segment_pause is not None:
        recipe.append({"segment_pause": segment_pause})
    key = hashlib.sha256(json.dumps(recipe, ensure_ascii=False).encode()).hexdigest()
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "speech-" + key},
        )
    existing = db.scalar(select(GeneratedAudio).where(GeneratedAudio.cache_key == key))
    if existing:
        return existing
    # Reuse the genuine cached voice after tightening its pauses. A pacing edit
    # must not make listeners pay for identical words to be synthesized again.
    if voice == "energetic" and (compact_pauses or segment_pause == 0.25):
        legacy_recipe = (
            [4, config, voice, parts]
            if compact_pauses
            else [3, config, voice, parts, {"segment_pause": 0.55}]
        )
        legacy_key = hashlib.sha256(json.dumps(legacy_recipe, ensure_ascii=False).encode()).hexdigest()
        legacy = db.scalar(select(GeneratedAudio).where(GeneratedAudio.cache_key == legacy_key))
        if legacy:
            retime_trump_cache(db, legacy)
            legacy.cache_key = key
            db.flush()
            return legacy
    if (
        config[0] == "elevenlabs"
        and segment_pause is None
        and len(parts) > 1
        and os.getenv("ELEVENLABS_BATCH_TTS", "1") == "1"
    ):
        pauses = [
            (
                (0.18 if compact_pauses else 0.7)
                if getattr(left, "story_id", None) != getattr(right, "story_id", None)
                else (0.12 if compact_pauses else 0.32)
            )
            for left, right in zip(segments, segments[1:])
        ]
        pcm, boundaries = render_aligned(db, parts, config, reference_id, pauses=pauses)
    else:
        pcm, boundaries = bytearray(), []
        for index, (text, lang) in enumerate(parts):
            start = len(pcm) / (2 * RATE)
            pcm.extend(render_segment(db, text, lang, voice, config, reference_id))
            pause = (
                segment_pause
                if segment_pause is not None and index < len(parts) - 1
                else 0.2
            )
            pcm.extend(b"\0\0" * round(RATE * pause))
            boundaries.append([start, len(pcm) / (2 * RATE)])
    if compact_pauses:
        pcm, boundaries = trim_long_pauses(bytes(pcm), boundaries)
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
