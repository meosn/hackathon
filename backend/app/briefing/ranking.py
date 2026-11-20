import json
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import preferences
from app.news.models import Story, StoryTopic
from app.news.service import summaries
from .models import ListeningHistory, UserFeedback

WEIGHTS = {
    "interest": 0.34,
    "importance": 0.22,
    "recency": 0.14,
    "urgency": 0.08,
    "source": 0.08,
    "unheard": 0.07,
    "feedback": 0.07,
}
DAYS = {"day": 1, "week": 7, "month": 30}


def parse_date(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    return (
        result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)
    )


def ranked(
    stories,
    prefs,
    *,
    period="week",
    topic=None,
    selected=None,
    heard=(),
    feedback=None,
    now=None,
):
    now = now or datetime.now(UTC)
    feedback = feedback or {}
    weights = WEIGHTS | json.loads(os.getenv("RANK_WEIGHTS") or "{}")
    interests = {
        word.casefold().replace(" ", "_") for word in prefs.get("interests", [])
    }
    preferred = set(prefs.get("preferred_sources", []))
    excluded = set(prefs.get("excluded_sources", []))
    topic = topic.casefold().replace(" ", "_") if topic else None
    results = []
    for story in stories:
        event_at = parse_date(story["event_at"])
        age = (now - event_at).total_seconds() / 86400
        topics = {
            name.casefold().replace(" ", "_")
            for name in story["topics"] + [story["category"]]
        }
        allowed = set(story["source_ids"]) - excluded
        if not allowed or (topic and topic not in topics):
            continue
        if selected:
            if story["id"] not in selected:
                continue
        elif age < 0 or event_at < now - timedelta(days=DAYS[period]):
            continue
        values = {
            "interest": float(bool(topics & interests)),
            "importance": story["importance"],
            "urgency": story["urgency"],
            "recency": 1 / (1 + max(0, age) / 3),
            "source": float(bool(allowed & preferred)),
            "unheard": float(story["id"] not in heard),
            "feedback": feedback.get(story["id"], 0),
        }
        score = sum(weights[k] * v for k, v in values.items())
        results.append((score, story))
    results.sort(
        key=lambda pair: (
            -pair[0],
            -parse_date(pair[1]["event_at"]).timestamp(),
            pair[1]["id"],
        )
    )
    # Keep one globally critical story in the first three without overriding explicit filters.
    critical = next(
        (
            pair
            for pair in results
            if pair[1]["urgency"] >= 0.9 and pair[1]["importance"] >= 0.8
        ),
        None,
    )
    if critical and results.index(critical) > 2:
        results.remove(critical)
        results.insert(2, critical)
    return [story for _, story in results]


def recommendations(
    db: Session, user_id: str, *, period="week", topic=None, selected=None
):
    now = datetime.now(UTC)
    query = select(Story).where(Story.archived.is_(False))
    if selected:
        query = query.where(Story.id.in_(selected))
    else:
        query = query.where(
            Story.event_at.between(now - timedelta(days=DAYS[period]), now)
        )
    if topic:
        topic = topic.casefold().replace(" ", "_")
        belongs_to_topic = (
            select(StoryTopic.id)
            .where(StoryTopic.story_id == Story.id, StoryTopic.name == topic)
            .exists()
        )
        query = query.where((Story.category == topic) | belongs_to_topic)
    stories = db.scalars(query).all()
    ids = [s.id for s in stories]
    heard = set(
        db.scalars(
            select(ListeningHistory.story_id).where(
                ListeningHistory.user_id == user_id, ListeningHistory.story_id.in_(ids)
            )
        )
    )
    feedback = dict(
        db.execute(
            select(UserFeedback.story_id, UserFeedback.score).where(
                UserFeedback.user_id == user_id, UserFeedback.story_id.in_(ids)
            )
        ).all()
    )
    return ranked(
        summaries(db, stories),
        preferences(db, user_id),
        heard=heard,
        feedback=feedback,
        period=period,
        topic=topic,
        selected=selected,
        now=now,
    )
