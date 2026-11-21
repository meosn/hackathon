"""One prepared baseline per local calendar day and content preference snapshot."""

import os
import hashlib
import json
from sqlalchemy import select
from app.accounts import User, Schedule, preferences
from app.db import utcnow
from app.timezones import resolve_timezone
from .contracts import BriefingRequest
from .models import Briefing, BriefingItem, BriefingSegment
from .models import ListeningHistory, UserFeedback
from .service import create_briefing, lock_briefing

CONTENT_KEYS = (
    "language",
    "duration_minutes",
    "depth",
    "interests",
    "preferred_sources",
    "excluded_sources",
)


def content_key(prefs, kind):
    settings = {key: prefs[key] for key in CONTENT_KEYS}
    settings.update(
        kind=kind,
        period=os.getenv("DAILY_NEWS_PERIOD", "day") if kind == "day" else "week",
        edition=os.getenv("NEWS_EDITION_VERSION", ""),
        recipe="personalized-v4",
    )
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[
        :16
    ]


def daily_key(user_id, prefs, today, kind="day"):
    speaker = prefs.get("prepared_voice_key", prefs["voice_profile_id"])
    voice_key = hashlib.sha256(speaker.encode()).hexdigest()[:12]
    family, label = ("daily", "top3") if kind == "day" else ("weekly", "week")
    edition = os.getenv("NEWS_EDITION_VERSION", "")
    return (
        f"{family}/{user_id}/{today}/{label}/paced-v3-{content_key(prefs, kind)}-{voice_key}"
        + (f"/{edition}" if edition else "")
    )


def ensure_prepared(db, user_id, kind="day", now=None):
    from app.jobs import queue_record
    from app.messaging import emit
    from . import characters, service

    prefs = preferences(db, user_id)
    user = db.get(User, user_id)
    narrator = characters.selected(db, user)
    prefs = {
        **prefs,
        "prepared_voice_key": narrator["profile_id"]
        + (
            "/" + characters.revision(user)
            if narrator["profile_id"] == "custom"
            else ""
        ),
    }
    today = (now or utcnow()).astimezone(resolve_timezone(prefs["timezone"])).date()
    key = daily_key(user_id, prefs, today, kind)
    existing = db.scalar(select(Briefing).where(Briefing.schedule_key == key))
    if existing:
        return existing
    content = f"{today}/{kind}/{content_key(prefs, kind)}"
    source = db.scalar(
        select(Briefing)
        .where(
            Briefing.user_id == user_id,
            Briefing.status.in_(["script_ready", "audio_generating", "completed"]),
            Briefing.request["prepared_content_key"].as_string() == content,
        )
        .order_by(Briefing.created_at.desc())
        .limit(1)
    )
    personalized = db.scalar(
        select(ListeningHistory.id).where(ListeningHistory.user_id == user_id).limit(1)
    ) or db.scalar(
        select(UserFeedback.id)
        .where(UserFeedback.user_id == user_id, UserFeedback.score != 0)
        .limit(1)
    )
    if (
        not source
        and not personalized
        and not prefs["excluded_sources"]
        and not prefs["preferred_sources"]
    ):
        for profile in ("tech", "finance"):
            template = db.scalar(
                select(User).where(User.email == f"daily-{profile}@system.invalid")
            )
            if not template or template.id == user_id:
                continue
            tp = preferences(db, template.id)
            if any(tp[key] != prefs[key] for key in CONTENT_KEYS):
                continue
            source = db.scalar(
                select(Briefing).where(
                    Briefing.user_id == template.id,
                    Briefing.status.in_(
                        ["script_ready", "audio_generating", "completed"]
                    ),
                    Briefing.schedule_key == daily_key(template.id, tp, today, kind),
                )
            )
            if source:
                break
    item = create_briefing(
        db,
        user_id,
        BriefingRequest(
            voice_profile_id=narrator["profile_id"],
            period=os.getenv("DAILY_NEWS_PERIOD", "day") if kind == "day" else "week",
            story_limit=3 if kind == "day" else None,
        ),
        schedule_key=key,
    )
    item = lock_briefing(db, item.id)
    if item.status != "queued":
        return item
    item.request = {
        **item.request,
        "prepared_content_key": content,
        "prepared_voice_key": prefs["prepared_voice_key"],
        "prepared_kind": kind,
    }
    item.title = service.TITLES[item.language][kind]
    if source:
        same_voice = (
            source.status == "completed"
            and source.audio_id is not None
            and (
                source.request.get("prepared_voice_key") == prefs["prepared_voice_key"]
            )
        )
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
        for row in service.segments_for(db, source.id):
            values = service.segment_view(row)
            values.pop("id")
            if not same_voice:
                values.update(start_seconds=0, end_seconds=0)
            db.add(BriefingSegment(briefing_id=item.id, **values))
        item.duration_seconds = source.duration_seconds
        item.request = {**item.request, "source_briefing_id": source.id}
        if same_voice:
            item.status, item.audio_id = "completed", source.audio_id
            emit(db, "briefing.audio.ready", item.id)
            emit(db, "briefing.completed", item.id)
        else:
            item.status = "script_ready"
            queue_record(db, "voice", item.id)
            emit(db, "briefing.script.ready", item.id)
            emit(db, "briefing.audio.requested", item.id)
        db.flush()
        return item
    queue_record(db, "briefing", item.id)
    return item


def ensure_daily(db, user_id, now=None):
    return ensure_prepared(db, user_id, "day", now)


def ensure_weekly(db, user_id, now=None):
    return ensure_prepared(db, user_id, "week", now)


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
        ensure_weekly(db, user.id)
