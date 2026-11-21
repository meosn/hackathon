"""Private voice collection; shared presets are never deleted for other listeners."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from .accounts import User, VoiceProfile, ACTIVE_VOICES, PREMIUM_VOICES, preferences, set_preferences, require_voice_access
from .auth import current_user
from .db import Record, get_db

DEFAULT_FAVORITES = {"professional", "energetic"}

class ListenerVoice(Record):
    __tablename__ = "listener_voices"
    __table_args__ = (UniqueConstraint("user_id", "preset_slug"), UniqueConstraint("user_id", "provider_voice_id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    preset_slug: Mapped[str | None] = mapped_column(String(80))
    provider_voice_id: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(100))
    persona: Mapped[str] = mapped_column(String(600), default="Natural, conversational delivery.")
    favorite: Mapped[bool] = mapped_column(Boolean, default=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)


def remember(db, user, rename=False):
    if not user.custom_voice_id:
        return None
    row = db.scalar(select(ListenerVoice).where(ListenerVoice.user_id == user.id, ListenerVoice.provider_voice_id == user.custom_voice_id))
    if not row:
        row = ListenerVoice(user_id=user.id, provider_voice_id=user.custom_voice_id, name=user.custom_voice_name, persona=user.custom_voice_persona)
        db.add(row)
    if rename:
        row.name, row.persona = user.custom_voice_name, user.custom_voice_persona
    db.flush()
    return row


def collection(db, user):
    remember(db, user)
    prefs = preferences(db, user.id)
    entries = db.scalars(select(ListenerVoice).where(ListenerVoice.user_id == user.id).order_by(ListenerVoice.created_at)).all()
    overrides = {v.preset_slug: v for v in entries if v.preset_slug}
    result = []
    for voice in db.scalars(select(VoiceProfile).where(VoiceProfile.slug.in_(ACTIVE_VOICES)).order_by(VoiceProfile.name)):
        entry = overrides.get(voice.slug)
        result.append(dict(id=voice.slug, name=voice.name, description=voice.description, custom=False,
            favorite=entry.favorite if entry else voice.slug in DEFAULT_FAVORITES, hidden=bool(entry and entry.hidden),
            selected=not user.custom_voice_active and prefs["voice_profile_id"] == voice.slug,
            locked=voice.slug in PREMIUM_VOICES and not user.is_premium))
    for voice in entries:
        if voice.preset_slug:
            continue
        result.append(dict(id="custom:" + voice.id, name=voice.name, description="Your custom voice", custom=True,
            favorite=voice.favorite, hidden=voice.hidden, selected=bool(user.custom_voice_active and user.custom_voice_id == voice.provider_voice_id), locked=False))
    return result


def entry_for(db, user, key):
    if key.startswith("custom:"):
        row = db.scalar(select(ListenerVoice).where(ListenerVoice.user_id == user.id, ListenerVoice.id == key[7:], ListenerVoice.preset_slug.is_(None)))
        if not row:
            raise HTTPException(404, "Voice not found")
        return row
    preset = db.scalar(select(VoiceProfile).where(VoiceProfile.slug == key, VoiceProfile.slug.in_(ACTIVE_VOICES)))
    if not preset:
        raise HTTPException(404, "Voice not found")
    row = db.scalar(select(ListenerVoice).where(ListenerVoice.user_id == user.id, ListenerVoice.preset_slug == key))
    if not row:
        row = ListenerVoice(user_id=user.id, preset_slug=key, name=preset.name, favorite=key in DEFAULT_FAVORITES)
        db.add(row)
        db.flush()
    return row


class LibraryPatch(BaseModel):
    favorite: bool | None = None
    hidden: bool | None = None

router = APIRouter()

@router.get("/voice-library")
def library(db=Depends(get_db), user=Depends(current_user)):
    result = collection(db, user)
    db.commit()
    return result

@router.patch("/voice-library/{key}")
def change_voice(key: str, body: LibraryPatch, db=Depends(get_db), user=Depends(current_user)):
    row = entry_for(db, user, key)
    if body.favorite is not None:
        row.favorite = body.favorite
        if body.favorite:
            row.hidden = False
    if body.hidden is not None:
        row.hidden = body.hidden
        if row.hidden:
            row.favorite = False
    db.commit()
    return collection(db, user)

@router.post("/voice-library/{key}/select")
def choose_voice(key: str, db=Depends(get_db), user=Depends(current_user)):
    row = entry_for(db, user, key)
    if row.hidden:
        raise HTTPException(422, "Restore this voice to your collection first")
    if row.preset_slug:
        require_voice_access(user, row.preset_slug)
        user.custom_voice_active = False
        set_preferences(db, user.id, {"voice_profile_id": row.preset_slug, **({"voice_engine": "elevenlabs"} if row.preset_slug == "energetic" else {})})
    else:
        user.custom_voice_id, user.custom_voice_name, user.custom_voice_persona = row.provider_voice_id, row.name, row.persona
        user.custom_voice_active = True
        user.custom_voice_sample = None
        set_preferences(db, user.id, {"voice_engine": "elevenlabs"})
    db.commit()
    return collection(db, user)

@router.delete("/voice-library/{key}", status_code=204)
def remove_voice(key: str, db=Depends(get_db), user=Depends(current_user)):
    row = entry_for(db, user, key)
    if row.preset_slug:
        row.hidden, row.favorite = True, False
        if preferences(db, user.id)["voice_profile_id"] == row.preset_slug and not user.custom_voice_active:
            choices = [v for v in collection(db, user) if not v["custom"] and not v["hidden"] and not v["locked"]]
            fallback = choices[0]["id"] if choices else "professional"
            set_preferences(db, user.id, {"voice_profile_id": fallback, **({"voice_engine": "elevenlabs"} if fallback == "energetic" else {})})
    else:
        if user.custom_voice_id == row.provider_voice_id:
            user.custom_voice_id, user.custom_voice_sample, user.custom_voice_active = None, None, False
            user.custom_voice_name = "Custom"
        db.delete(row)
    db.commit()
