"""Resolve shared character defaults and private listener voices on the server."""

from sqlalchemy import select
from fastapi import HTTPException
import hashlib
from app.accounts import VoiceProfile, preferences, require_voice_access


def revision(user):
    return hashlib.sha256((user.custom_voice_id or "").encode()).hexdigest()[:16]


def selected(db, user):
    prefs = preferences(db, user.id)
    profile = db.scalar(
        select(VoiceProfile).where(VoiceProfile.slug == prefs["voice_profile_id"])
    )
    if not profile:
        raise HTTPException(422, "Choose an existing character")
    require_voice_access(user, profile.slug)
    custom = user.custom_voice_active and user.custom_voice_id
    return {
        "profile_id": "custom" if custom else profile.slug,
        "voice_id": user.custom_voice_id if custom else profile.elevenlabs_voice_id,
        "openai_voice": profile.openai_voice,
        "persona": (user.custom_voice_persona if custom else profile.persona)
        + " Speak at a relaxed conversational pace. Pause naturally at punctuation, between sentences, and longer between stories. Never run sentences together or rush through headlines.",
        "language": prefs["language"],
    }
