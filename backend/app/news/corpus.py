"""Keep live public reporting separate from fixtures and the imported archive."""

import os
from sqlalchemy import select, func
from .models import Article, IngestionJob, Story, StoryArticle

LIVE_KINDS = ("source", "rss", "crawl")


def live():
    return os.getenv("ACTIVE_CORPUS") == "live"


def live_publication_window(start=None, end=None):
    query = (
        select(StoryArticle.id)
        .join(Article, Article.id == StoryArticle.article_id)
        .join(IngestionJob, IngestionJob.id == Article.job_id)
        .where(
            StoryArticle.story_id == Story.id,
            IngestionJob.kind.in_(LIVE_KINDS),
            Article.is_synthetic.is_(False),
        )
    )
    if start is not None:
        query = query.where(Article.published_at >= start)
    if end is not None:
        query = query.where(Article.published_at <= end)
    return query.exists()


def restrict_stories(query):
    if os.getenv("ACTIVE_CORPUS") in {"licensed", "live"}:
        query = query.where(Story.is_synthetic.is_(False))
    return query.where(live_publication_window()) if live() else query


def latest_publication_time():
    return (
        select(func.max(Article.published_at))
        .join(StoryArticle, StoryArticle.article_id == Article.id)
        .where(StoryArticle.story_id == Story.id)
        .correlate(Story)
        .scalar_subquery()
    )
