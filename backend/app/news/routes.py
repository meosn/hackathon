import base64
import json
import os
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.auth import admin_user, current_user
from app.db import get_db
from app.news import service
from app.news.models import (
    Article,
    IngestionJob,
    Source,
    Story,
    StoryArticle,
    StoryTopic,
)

router = APIRouter(tags=["news"], dependencies=[Depends(current_user)])
DB = Annotated[Session, Depends(get_db)]


class SourceInfo(BaseModel):
    id: str
    name: str
    is_synthetic: bool


class ArticleInfo(BaseModel):
    id: str
    title: str
    source_id: str
    source_name: str
    url: str
    language: str
    published_at: datetime
    is_synthetic: bool
    author: str | None
    near_duplicate_of: str | None


class EvidenceInfo(BaseModel):
    article_id: str
    source_id: str
    source_name: str
    url: str
    excerpt: str
    start: int
    end: int
    is_synthetic: bool


class FactInfo(BaseModel):
    id: str
    text: str
    language: str
    status: Literal["supported", "conflicting", "insufficient_evidence", "rejected"]
    contradiction: bool
    evidence: list[EvidenceInfo]


class DisagreementInfo(BaseModel):
    id: str
    description: str
    fact_ids: list[str]


class StoryInfo(BaseModel):
    publisher_count: int = 0
    corroborated_claim_count: int = 0
    coverage_status: str = "single_source"
    id: str
    title: str
    summary: str
    category: str
    topics: list[str]
    importance: float
    urgency: float
    event_at: datetime
    updated_at: datetime
    source_count: int
    article_count: int
    languages: list[str]
    source_ids: list[str]
    is_synthetic: bool


class Detail(StoryInfo):
    articles: list[ArticleInfo]
    facts: list[FactInfo]
    disagreements: list[DisagreementInfo]


class Page(BaseModel):
    items: list[StoryInfo]
    next_cursor: str | None


class TopicInfo(BaseModel):
    name: str
    count: int


@router.get("/sources", response_model=list[SourceInfo])
def sources(db: DB):
    query = select(Source).order_by(Source.name)
    if os.getenv("ACTIVE_CORPUS") in {"licensed", "live"}:
        query = query.where(Source.is_synthetic.is_(False))
    if os.getenv("ACTIVE_CORPUS") == "live":
        from .corpus import LIVE_KINDS

        query = query.where(
            Source.id.in_(
                select(Article.source_id)
                .join(IngestionJob, IngestionJob.id == Article.job_id)
                .where(IngestionJob.kind.in_(LIVE_KINDS))
            )
        )
    return [
        dict(id=s.id, name=s.name, is_synthetic=s.is_synthetic)
        for s in db.scalars(query)
    ]


@router.get("/topics", response_model=list[TopicInfo])
def topics(db: DB):
    query = (
        select(StoryTopic.name, func.count())
        .join(Story, Story.id == StoryTopic.story_id)
        .where(Story.archived.is_(False))
        .group_by(StoryTopic.name)
        .order_by(StoryTopic.name)
    )
    from .corpus import restrict_stories

    query = restrict_stories(query)
    rows = db.execute(query)
    return [dict(name=name, count=count) for name, count in rows]


@router.get("/stories", response_model=Page)
def stories(
    db: DB,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    topic: str | None = Query(None, max_length=80),
    language: str | None = Query(None, max_length=12),
    importance_min: float | None = Query(None, ge=0, le=1),
    source: str | None = Query(None, max_length=180),
    search: str | None = Query(None, max_length=250),
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = Query(None, max_length=400),
    sort: Literal["recent", "importance", "oldest"] = "recent",
):
    from .corpus import restrict_stories, live, latest_publication_time

    stmt = restrict_stories(select(Story).where(Story.archived.is_(False)))
    published = latest_publication_time() if live() else Story.event_at
    if date_from:
        stmt = stmt.where(published >= date_from)
    if date_to:
        stmt = stmt.where(published <= date_to)
    if topic:
        stmt = stmt.where(
            Story.id.in_(select(StoryTopic.story_id).where(StoryTopic.name == topic))
        )
    if language or source:
        ids = select(StoryArticle.story_id).join(
            Article, Article.id == StoryArticle.article_id
        )
        if language:
            ids = ids.where(Article.language == language)
        if source:
            ids = ids.join(Source, Source.id == Article.source_id).where(
                or_(Source.id == source, Source.name == source)
            )
        stmt = stmt.where(Story.id.in_(ids))
    if importance_min is not None:
        stmt = stmt.where(Story.importance >= importance_min)
    if search:
        stmt = stmt.where(
            or_(
                Story.title.icontains(search, autoescape=True),
                Story.summary.icontains(search, autoescape=True),
            )
        )
    col = Story.importance if sort == "importance" else published
    if cursor:
        try:
            mode, key, last_id = json.loads(base64.urlsafe_b64decode(cursor))
            if sort != mode or not isinstance(last_id, str):
                raise ValueError
            key = float(key) if sort == "importance" else datetime.fromisoformat(key)
        except (TypeError, ValueError, UnicodeError):
            raise HTTPException(422, "Invalid story cursor")
        boundary = col > key if sort == "oldest" else col < key
        stmt = stmt.where(or_(boundary, and_(col == key, Story.id > last_id)))
    ordered = stmt.order_by(
        col.asc() if sort == "oldest" else col.desc(), Story.id
    ).limit(limit + 1)
    rows = db.scalars(ordered).all()
    items = service.summaries(db, rows[:limit])
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        key = items[-1]["importance"] if sort == "importance" else items[-1]["event_at"]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([sort, key, last.id]).encode()
        ).decode()
    return dict(items=items, next_cursor=next_cursor)


def detail_or_404(db, story_id):
    result = service.story_detail(db, story_id)
    if not result:
        raise HTTPException(404, "Story not found")
    if not result["is_synthetic"]:
        # Licensed stories expose short quotations. Full source text stays private.
        counts = {}
        visible = []
        for fact in result["facts"]:
            evidence = fact["evidence"]
            ids = {e["article_id"] for e in evidence}
            if len(fact["text"]) <= 280 and all(counts.get(aid, 0) < 2 for aid in ids):
                visible.append(fact)
                for aid in ids:
                    counts[aid] = counts.get(aid, 0) + 1
        result["facts"] = visible
        result["summary"] = result["summary"][:280]
    return result


@router.get("/stories/{story_id}", response_model=Detail)
def detail(db: DB, story_id: str):
    return detail_or_404(db, story_id)


@router.get("/stories/{story_id}/articles", response_model=list[ArticleInfo])
def articles(db: DB, story_id: str):
    return detail_or_404(db, story_id)["articles"]


@router.get("/articles/{article_id}")
def article_by_id(db: DB, article_id: str):
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    return {
        **service.article_view(article, db.get(Source, article.source_id)),
        "content": article.content if article.is_synthetic else "",
        "full_text_available": article.is_synthetic,
    }


@router.get("/stories/{story_id}/facts", response_model=list[FactInfo])
def facts(db: DB, story_id: str):
    return detail_or_404(db, story_id)["facts"]


@router.get(
    "/stories/{story_id}/source-comparison", response_model=list[DisagreementInfo]
)
def compare(db: DB, story_id: str):
    return detail_or_404(db, story_id)["disagreements"]


class JobInput(BaseModel):
    kind: Literal["fixture", "dataset", "rss", "crawl", "source"] = "fixture"
    locator: str | None = Field(None, max_length=2000)


def job_result(job):
    return dict(
        id=job.id,
        job_id=job.id,
        kind=job.kind,
        status=job.status,
        received=job.received,
        duplicates=job.duplicates,
        analyzed=job.analyzed,
        error=job.error,
    )


@router.post("/ingestion/jobs", status_code=202, dependencies=[Depends(admin_user)])
def submit_job(db: DB, body: JobInput):
    from app.jobs import queue_record, publish

    try:
        job = service.create_job(db, body.kind, body.locator)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    task_id = queue_record(db, "ingestion", job.id).id
    db.commit()
    publish(task_id)
    return job_result(job)


@router.get("/ingestion/jobs/{job_id}", dependencies=[Depends(admin_user)])
def ingestion_job(db: DB, job_id: str):
    job = db.get(IngestionJob, job_id)
    if not job:
        raise HTTPException(404, "Ingestion job not found")
    return job_result(job)


class Merge(BaseModel):
    into_story_id: str


class Split(BaseModel):
    article_ids: list[str] = Field(min_length=1, max_length=100)


def get_story(db, id):
    story = db.get(Story, id)
    if not story or story.archived:
        raise HTTPException(404, "Active story not found")
    return story


@router.post(
    "/stories/{story_id}/merge",
    dependencies=[Depends(admin_user)],
    response_model=Detail,
)
def merge(db: DB, story_id: str, body: Merge):
    source, target = get_story(db, story_id), get_story(db, body.into_story_id)
    try:
        service.move_articles(
            db, source, target, [a.id for a in service.story_articles(db, source.id)]
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    return detail_or_404(db, target.id)


@router.post(
    "/stories/{story_id}/split",
    dependencies=[Depends(admin_user)],
    response_model=Detail,
)
def split(db: DB, story_id: str, body: Split):
    source = get_story(db, story_id)
    valid = {a.id: a for a in service.story_articles(db, source.id)}
    requested = set(body.article_ids)
    if not requested < valid.keys():
        raise HTTPException(422, "Select a proper subset of this story's articles")
    target = service.new_story(db, valid[body.article_ids[0]])
    try:
        service.move_articles(db, source, target, requested)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    return detail_or_404(db, target.id)


@router.get("/stories/{story_id}/importance")
def importance(db: DB, story_id: str):
    from .editorial import assess_story
    story = db.get(Story, story_id)
    if not story or story.archived:
        raise HTTPException(404, "Story not found")
    return assess_story(db, story)
