"""Transfer listener reactions to future stories about the same topics."""

from collections import defaultdict
from sqlalchemy import select
from app.db import utcnow
from app.news.models import Story, StoryTopic
from .models import UserFeedback, ListeningHistory


def topic_affinities(db, user_id):
    reactions = db.execute(
        select(UserFeedback.story_id, UserFeedback.score, UserFeedback.created_at)
        .where(UserFeedback.user_id == user_id, UserFeedback.score != 0)
        .order_by(UserFeedback.created_at.desc())
        .limit(100)
    ).all()
    listened = db.execute(
        select(ListeningHistory.story_id, ListeningHistory.created_at)
        .where(ListeningHistory.user_id == user_id)
        .order_by(ListeningHistory.created_at.desc())
        .limit(100)
    ).all()
    ids = {row[0] for row in reactions} | {row[0] for row in listened}
    if not ids:
        return {}
    labels = defaultdict(set)
    for sid, category in db.execute(
        select(Story.id, Story.category).where(Story.id.in_(ids))
    ):
        labels[sid].add(category)
    for sid, topic in db.execute(
        select(StoryTopic.story_id, StoryTopic.name).where(StoryTopic.story_id.in_(ids))
    ):
        labels[sid].add(topic)
    values = defaultdict(float)
    explicit = {row[0] for row in reactions}
    signals = [(sid, 2 * score, at) for sid, score, at in reactions]
    signals.extend((sid, 0.2, at) for sid, at in listened if sid not in explicit)
    now = utcnow()
    for sid, strength, at in signals:
        age = max(0, (now - at.replace(tzinfo=now.tzinfo)).total_seconds() / 86400)
        for topic in labels[sid]:
            values[topic.casefold().replace(" ", "_")] += strength * 0.5 ** (age / 30)
    return {topic: max(-1, min(1, value)) for topic, value in values.items()}
