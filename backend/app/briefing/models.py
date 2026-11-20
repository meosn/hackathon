"""Listener-owned playback and conversation records."""

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Record


class Briefing(Record):
    __tablename__ = "briefings"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    language: Mapped[str] = mapped_column(String(10))
    voice_profile_id: Mapped[str] = mapped_column(String(80))
    request: Mapped[dict] = mapped_column(JSON)
    schedule_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    audio_id: Mapped[str | None] = mapped_column(
        ForeignKey("generated_audio.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(String(400))


class BriefingItem(Record):
    __tablename__ = "briefing_items"
    __table_args__ = (UniqueConstraint("briefing_id", "position"),)
    briefing_id: Mapped[str] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), index=True
    )
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(600))
    position: Mapped[int] = mapped_column(Integer)


class BriefingSegment(Record):
    __tablename__ = "briefing_segments"
    __table_args__ = (UniqueConstraint("briefing_id", "position"),)
    briefing_id: Mapped[str] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), index=True
    )
    story_id: Mapped[str | None] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10))
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_article_ids: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    verification_status: Mapped[str] = mapped_column(String(30))
    start_seconds: Mapped[float] = mapped_column(Float, default=0)
    end_seconds: Mapped[float] = mapped_column(Float, default=0)


class GeneratedAudio(Record):
    __tablename__ = "generated_audio"
    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    object_key: Mapped[str] = mapped_column(String(200))
    duration_seconds: Mapped[float] = mapped_column(Float)
    boundaries: Mapped[list] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String(60))


class ListeningHistory(Record):
    __tablename__ = "listening_history"
    __table_args__ = (UniqueConstraint("user_id", "story_id"),)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))


class UserFeedback(Record):
    __tablename__ = "user_feedback"
    __table_args__ = (UniqueConstraint("user_id", "story_id"),)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column(Integer)


class Conversation(Record):
    __tablename__ = "conversations"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    briefing_id: Mapped[str | None] = mapped_column(
        ForeignKey("briefings.id", ondelete="SET NULL")
    )
    story_id: Mapped[str | None] = mapped_column(
        ForeignKey("stories.id", ondelete="SET NULL")
    )
    topic: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(10))


class ConversationMessage(Record):
    __tablename__ = "conversation_messages"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(12))
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(35))
    story_id: Mapped[str | None] = mapped_column(
        ForeignKey("stories.id", ondelete="SET NULL")
    )
    briefing_id: Mapped[str | None] = mapped_column(
        ForeignKey("briefings.id", ondelete="SET NULL")
    )
    citations: Mapped[list] = mapped_column(JSON, default=list)
    action: Mapped[dict] = mapped_column(JSON, default=dict)
