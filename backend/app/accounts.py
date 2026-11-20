from datetime import date
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column
from fastapi import HTTPException
from .db import Record


class User(Record):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(90))
    password_hash: Mapped[str]
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_voice_id: Mapped[str | None] = mapped_column(String(128))
    custom_voice_active: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_voice_name: Mapped[str] = mapped_column(String(80), default="Custom")
    custom_voice_persona: Mapped[str] = mapped_column(String(600), default="Natural, conversational delivery.")
    custom_voice_sample: Mapped[bytes | None] = mapped_column(
        LargeBinary, deferred=True
    )


class VoiceProfile(Record):
    __tablename__ = "voice_profiles"
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str]
    description: Mapped[str]
    elevenlabs_voice_id: Mapped[str | None] = mapped_column(String(128))
    openai_voice: Mapped[str] = mapped_column(String(24), default="marin")
    persona: Mapped[str] = mapped_column(default="")


class UserPreference(Record):
    __tablename__ = "user_preferences"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    language: Mapped[str] = mapped_column(String(5), default="en")
    duration_minutes: Mapped[int] = mapped_column(default=5)
    voice_profile_id: Mapped[str] = mapped_column(
        ForeignKey("voice_profiles.slug"), default="professional"
    )
    timezone: Mapped[str] = mapped_column(default="UTC")
    depth: Mapped[str] = mapped_column(default="standard")
    discussion_model: Mapped[str] = mapped_column(String(24), default="configured")
    voice_engine: Mapped[str] = mapped_column(String(24), default="openai")


class UserInterest(Record):
    __tablename__ = "user_interests"
    __table_args__ = (UniqueConstraint("user_id", "topic"),)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str] = mapped_column(String(100))


class UserSource(Record):
    __tablename__ = "user_sources"
    __table_args__ = (UniqueConstraint("user_id", "source_id"),)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    excluded: Mapped[bool]


class Schedule(Record):
    __tablename__ = "briefing_schedules"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    time: Mapped[str] = mapped_column(String(5))
    timezone: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    last_local_date: Mapped[date | None] = mapped_column(Date)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def timezone_name(value):
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Unknown IANA time zone")
    return value


class PreferencePatch(Input):
    language: Literal["en", "de", "nl"] | None = None
    duration_minutes: int | None = Field(None, ge=1, le=30)
    voice_profile_id: str | None = Field(None, max_length=64)
    timezone: str | None = Field(None, max_length=80)
    depth: Literal["brief", "standard", "detailed"] | None = None
    discussion_model: Literal["grounded", "configured"] | None = None
    voice_engine: Literal["openai", "elevenlabs"] | None = None
    interests: list[str] | None = Field(None, max_length=50)
    preferred_sources: list[str] | None = Field(None, max_length=150)
    excluded_sources: list[str] | None = Field(None, max_length=150)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        return timezone_name(value) if value else value

    @field_validator("interests")
    @classmethod
    def valid_interests(cls, value):
        if value is None:
            return value
        topics = [s.strip().lower().replace(" ", "_") for s in value]
        if any(not s or len(s) > 100 for s in topics):
            raise ValueError("Each topic must contain 1–100 characters")
        return list(dict.fromkeys(topics))


VOICE_STYLES = [
    ("professional", "Professional news", "Even pacing and a clear newsroom delivery."),
    ("jarvis", "Studio assistant", "A composed, precise synthetic assistant."),
    ("energetic", "Energetic Speaker", "A brisk, animated delivery."),
    ("casual", "Street casual", "Relaxed conversational pacing."),
    ("cyberpunk", "Cyberpunk narrator", "Low, measured late-night narration."),
    ("gangsta", "CJ · GTA Gangsta", "A laid-back West Coast character with confident street delivery."),
]
VOICE_DEFAULTS = {
    "professional": ("onwK4e9ZLuTAKqWW03F9", "marin", "Speak with clear, composed newsroom delivery."),
    "jarvis": ("JBFqnCBsd6RMkjVDRZzb", "cedar", "Speak with calm precision, like a helpful studio assistant."),
    "energetic": ("TX3LPaxmHKxFdv7VOQHJ", "verse", "Speak like an energetic speaker: lively, upbeat and engaging, without shouting."),
    "casual": ("IKne3meq5aSn9XLyUdCD", "ash", "Speak in a relaxed, conversational tone."),
    "cyberpunk": ("nPczCjzI2devNBz1zQrb", "echo", "Use a low, measured, late-night delivery."),
    "gangsta": ("N2lVS1w4EtoT3dr4eOWO", "ash", "Use a fictional West Coast gangsta character style: laid-back, confident and streetwise. Light slang is welcome; do not claim to be a real performer or change news facts."),
}
DEMO_PROFILES = {
    "tech": {
        "name": "Technology enthusiast",
        "language": "en",
        "duration_minutes": 3,
        "interests": ["technology", "artificial_intelligence"],
        "voice_profile_id": "professional",
    },
    "finance": {
        "name": "Financial analyst",
        "language": "de",
        "duration_minutes": 6,
        "interests": ["finance", "markets", "economy"],
        "voice_profile_id": "professional",
    },
}


def seed_voices(db):
    for slug, name, description in VOICE_STYLES:
        row = db.scalar(select(VoiceProfile).where(VoiceProfile.slug == slug))
        if not row:
            row = VoiceProfile(slug=slug, name=name, description=description)
            db.add(row)
        if slug == "energetic" and row.name == "Energetic commentator":
            row.name = name
        voice_id, openai_voice, persona = VOICE_DEFAULTS[slug]
        if not row.elevenlabs_voice_id:
            row.elevenlabs_voice_id = voice_id
        if not row.persona:
            row.openai_voice, row.persona = openai_voice, persona
    db.flush()


def preferences(db, user_id):
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if not pref:
        pref = UserPreference(user_id=user_id)
        db.add(pref)
        db.flush()
    source_rows = db.scalars(
        select(UserSource).where(UserSource.user_id == user_id)
    ).all()
    return {
        **{
            key: getattr(pref, key)
            for key in (
                "language",
                "duration_minutes",
                "voice_profile_id",
                "timezone",
                "depth",
                "discussion_model",
                "voice_engine",
            )
        },
        "interests": sorted(
            db.scalars(
                select(UserInterest.topic).where(UserInterest.user_id == user_id)
            )
        ),
        "preferred_sources": sorted(s.source_id for s in source_rows if not s.excluded),
        "excluded_sources": sorted(s.source_id for s in source_rows if s.excluded),
    }


def set_preferences(db, user_id, changes):
    from .news.models import Source

    delta = PreferencePatch.model_validate(changes).model_dump(exclude_none=True)
    if delta.get("voice_engine") == "openai":
        owner = db.get(User, user_id)
        if owner:
            owner.custom_voice_active = False
    old = preferences(db, user_id)
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if "voice_profile_id" in delta and not db.scalar(
        select(VoiceProfile.id).where(VoiceProfile.slug == delta["voice_profile_id"])
    ):
        raise HTTPException(422, "Unknown voice")
    if "interests" in delta:
        db.execute(delete(UserInterest).where(UserInterest.user_id == user_id))
        db.add_all(
            UserInterest(user_id=user_id, topic=t) for t in delta.pop("interests")
        )
    if "preferred_sources" in delta or "excluded_sources" in delta:
        included = set(delta.pop("preferred_sources", old["preferred_sources"]))
        excluded = set(delta.pop("excluded_sources", old["excluded_sources"]))
        requested = included | excluded
        if included & excluded or requested != set(
            db.scalars(select(Source.id).where(Source.id.in_(requested)))
        ):
            raise HTTPException(422, "Choose distinct existing sources")
        db.execute(delete(UserSource).where(UserSource.user_id == user_id))
        db.add_all(
            UserSource(user_id=user_id, source_id=s, excluded=s in excluded)
            for s in requested
        )
    for key, value in delta.items():
        setattr(pref, key, value)
    db.flush()
    return preferences(db, user_id)


def demo_listener(db, profile):
    from .auth import hash_password
    from secrets import token_urlsafe

    template = DEMO_PROFILES[profile].copy()
    user = User(
        email=f"demo-{uuid4()}@demo.invalid",
        name=template.pop("name"),
        password_hash=hash_password(token_urlsafe(32)),
        is_demo=True,
    )
    db.add(user)
    db.flush()
    set_preferences(db, user.id, template)
    return user
