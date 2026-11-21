"""Short, cached voice samples using the same selected voice IDs as live chat."""

import os
import re
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from typing import Literal

from app.accounts import ACTIVE_VOICES, VoiceProfile, preferences, require_voice_access
from .contracts import Strict
from . import voice

PHRASES = {
    "en": "Hello! I'm your AI news host. This is how your briefing will sound.",
    "de": "Hallo! Ich bin Ihr KI-Nachrichtensprecher. So klingt Ihr Nachrichtenüberblick.",
    "nl": "Hallo! Ik ben uw AI-nieuwspresentator. Zo klinkt uw nieuwsoverzicht.",
}


class PreviewRequest(Strict):
    engine: Literal["openai", "elevenlabs"] | None = None
    language: Literal["en", "de", "nl"] | None = None


def render(db, user, slug, request):
    prefs = preferences(db, user.id)
    require_voice_access(user, slug)
    engine, language = (
        request.engine or prefs["voice_engine"],
        request.language or prefs["language"],
    )
    if slug == "custom":
        if not user.custom_voice_id:
            raise HTTPException(404, "Create your custom voice first.")
        if engine != "elevenlabs":
            raise HTTPException(422, "Custom voices use ElevenLabs.")
        voice_id = user.custom_voice_id
    else:
        profile = db.scalar(select(VoiceProfile).where(VoiceProfile.slug == slug))
        if slug not in ACTIVE_VOICES or not profile:
            raise HTTPException(404, "Voice not found")
        voice_id = (
            profile.openai_voice if engine == "openai" else profile.elevenlabs_voice_id
        )
    if os.getenv("TTS_PROVIDER", "local") in {"local", "mock"}:
        config = ("local", "espeak-ng", slug)
    elif engine == "openai":
        if not (os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")):
            raise HTTPException(503, "OpenAI voice previews are unavailable.")
        config = ("openai", "gpt-4o-mini-tts", voice_id)
    else:
        if not os.getenv("ELEVENLABS_API_KEY") or not voice_id:
            raise HTTPException(503, "ElevenLabs voice previews are unavailable.")
        config = (
            "elevenlabs",
            os.getenv("ELEVENLABS_MODEL") or "eleven_multilingual_v2",
            voice_id,
        )
    # Short samples must demonstrate clear phrasing even when a clone ignores
    # punctuation. Render complete sentences and join their PCM with real silence.
    sentences = (
        re.split(r"(?<=[.!?])\s+", PHRASES[language])
        if engine == "elevenlabs"
        else [PHRASES[language]]
    )
    return voice._render_audio(
        db,
        [SimpleNamespace(text=text, language=language) for text in sentences],
        slug,
        "voice-preview/" + user.id,
        config,
        segment_pause=(0.25 if slug == "energetic" else 0.55) if engine == "elevenlabs" else None,
    )


if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor
    from app.accounts import User
    from app.db import SessionLocal

    def warm(item):
        slug, engine, language = item
        with SessionLocal() as db:
            user = db.scalar(select(User).order_by(User.created_at).limit(1))
            if not user:
                raise RuntimeError("Create a listener before warming voice samples")
            audio = render(
                db, user, slug, PreviewRequest(engine=engine, language=language)
            )
            db.commit()
            return slug, engine, language, round(audio.duration_seconds, 2)

    jobs = [
        (slug, engine, language)
        for slug in sorted(ACTIVE_VOICES - {"gangsta"})
        for engine in ("openai", "elevenlabs")
        for language in PHRASES
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for item in pool.map(warm, jobs):
            print("Preview ready:", *item, flush=True)
