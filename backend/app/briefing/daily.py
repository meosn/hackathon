"""One immutable prepared baseline per listener's local calendar day."""

from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.accounts import User, Schedule, preferences
from app.db import utcnow
from .contracts import BriefingRequest
from .models import Briefing, BriefingItem, BriefingSegment
from .service import create_briefing, lock_briefing


def ensure_daily(db, user_id, now=None):
    from app.jobs import queue_record

    prefs = preferences(db, user_id)
    today = (now or utcnow()).astimezone(ZoneInfo(prefs["timezone"])).date()
    key = f"daily/{user_id}/{today}"
    existing = db.scalar(select(Briefing).where(Briefing.schedule_key == key))
    if existing:
        return existing
    item = create_briefing(
        db, user_id, BriefingRequest(voice_profile_id="professional"), schedule_key=key
    )
    item = lock_briefing(db, item.id)
    if item.status != "queued":
        return item
    # A prepared synthetic profile can share its audio while keeping history and conversation private.
    if not prefs["excluded_sources"] and not prefs["preferred_sources"]:
        for profile in ("tech", "finance"):
            template = db.scalar(
                select(User).where(User.email == f"daily-{profile}@system.invalid")
            )
            if not template or template.id == user_id:
                continue
            tp = preferences(db, template.id)
            if any(
                tp[k] != prefs[k]
                for k in ("language", "duration_minutes", "interests", "depth")
            ):
                continue
            source = db.scalar(
                select(Briefing).where(
                    Briefing.user_id == template.id,
                    Briefing.schedule_key == f"daily/{template.id}/{today}",
                    Briefing.status == "completed",
                )
            )
            if source:
                for row in db.scalars(
                    select(BriefingItem).where(BriefingItem.briefing_id == source.id)
                ):
                    db.add(
                        BriefingItem(
                            briefing_id=item.id,
                            story_id=row.story_id,
                            title=row.title,
                            position=row.position,
                        )
                    )
                columns = (
                    "story_id",
                    "position",
                    "text",
                    "language",
                    "claim_ids",
                    "source_article_ids",
                    "citations",
                    "verification_status",
                    "start_seconds",
                    "end_seconds",
                )
                for row in db.scalars(
                    select(BriefingSegment).where(
                        BriefingSegment.briefing_id == source.id
                    )
                ):
                    db.add(
                        BriefingSegment(
                            briefing_id=item.id, **{k: getattr(row, k) for k in columns}
                        )
                    )
                item.status, item.audio_id, item.duration_seconds = (
                    "completed",
                    source.audio_id,
                    source.duration_seconds,
                )
                from app.messaging import emit

                emit(db, "briefing.audio.ready", item.id)
                emit(db, "briefing.completed", item.id)
                db.flush()
                return item
    queue_record(db, "briefing", item.id)
    return item


def prepare_listener(db, user_id):
    """Initialize a listener before playback, and enable preparation on future mornings."""
    db.scalars(select(User).where(User.id == user_id).with_for_update()).one()
    if not db.scalar(select(Schedule.id).where(Schedule.user_id == user_id).limit(1)):
        db.add(
            Schedule(
                user_id=user_id,
                time="06:00",
                timezone=preferences(db, user_id)["timezone"],
                enabled=True,
            )
        )
    return ensure_daily(db, user_id)


def seed_templates(db):
    from app.accounts import demo_listener

    for profile in ("tech", "finance"):
        email = f"daily-{profile}@system.invalid"
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = demo_listener(db, profile)
            user.email = email
            db.flush()
        prepare_listener(db, user.id)
