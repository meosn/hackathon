import json
import os
import re
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
    "affinity": 0.3,
    "corroboration": 0.12,
}
DAYS = {"day": 1, "week": 7, "month": 30}


def news_now():
    if os.getenv("ACTIVE_CORPUS") == "live":
        return datetime.now(UTC)
    reference = os.getenv("NEWS_REFERENCE_TIME")
    return parse_date(reference) if reference else datetime.now(UTC)


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
    affinities=None,
    now=None,
):
    now = now or news_now()
    feedback = feedback or {}
    affinities = affinities or {}
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
            "interest": float(
                bool(topics & interests)
                or any(
                    re.search(
                        r"(?<!\w)" + re.escape(term.replace("_", " ")) + r"(?!\w)",
                        (
                            story.get("title", "") + " " + story.get("summary", "")
                        ).casefold(),
                    )
                    for term in interests
                )
            ),
            "importance": story["importance"],
            "urgency": story["urgency"],
            "recency": 1 / (1 + max(0, age) / 3),
            "source": float(bool(allowed & preferred)),
            "unheard": float(story["id"] not in heard),
            "feedback": feedback.get(story["id"], 0),
            "affinity": max(-1, min(1, sum(affinities.get(t, 0) for t in topics))),
            "corroboration": (
                (
                    1
                    if story.get("corroborated_claim_count", 0)
                    else 0.5 if story.get("publisher_count", 0) >= 2 else 0
                )
                if story.get("coverage_status") != "conflicting"
                else 0
            ),
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
    # Prefer at least one independently reported event when the filtered pool
    # contains one; single-publisher stories retain their explicit warning.
    compared = (
        lambda pair: pair[1].get("publisher_count", 0) >= 2
        and pair[1].get("coverage_status") != "conflicting"
    )
    corroborated = next((pair for pair in results if compared(pair)), None)
    if (
        corroborated
        and results.index(corroborated) > 2
        and not any(compared(pair) for pair in results[:3])
    ):
        results.remove(corroborated)
        results.insert(0, corroborated)
    # Reserve one slot for a learned interest without replacing the whole mix.
    learned = lambda pair: any(
        affinities.get(t.casefold().replace(" ", "_"), 0) > 0.4
        for t in pair[1]["topics"] + [pair[1]["category"]]
    )
    favorite = next((pair for pair in results if learned(pair)), None)
    if (
        favorite
        and results.index(favorite) > 2
        and not any(learned(pair) for pair in results[:3])
    ):
        results.remove(favorite)
        results.insert(1, favorite)
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
    now = news_now()
    from app.news.corpus import restrict_stories, live, live_publication_window

    query = select(Story).where(Story.archived.is_(False))
    if selected:
        if os.getenv("ACTIVE_CORPUS") in {"licensed", "live"}:
            query = query.where(Story.is_synthetic.is_(False))
        query = query.where(Story.id.in_(selected))
    else:
        query = restrict_stories(query)
        query = query.where(
            live_publication_window(now - timedelta(days=DAYS[period]), now)
            if live()
            else Story.event_at.between(now - timedelta(days=DAYS[period]), now)
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
    from .learning import topic_affinities

    prefs = preferences(db, user_id)
    return ranked(
        summaries(db, stories, excluded=prefs["excluded_sources"]),
        prefs,
        affinities=topic_affinities(db, user_id),
        heard=heard,
        feedback=feedback,
        period=period,
        topic=topic,
        selected=selected,
        now=now,
    )
