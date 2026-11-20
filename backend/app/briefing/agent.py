"""Build the bounded Sourcera context and authenticate an ElevenAgents session."""

import json
import os
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.accounts import preferences
from app.news.models import Article, IngestionJob, Story, StoryArticle
from app.news.service import story_detail
from . import service
from .contracts import AgentContextRequest
from .models import Briefing, BriefingItem
from .ranking import news_now

MAX_CONTEXT_BYTES = 12_000
AGENT_HOST = "api.elevenlabs.io"
AGENT_PATH = "/v1/convai/conversation"


def conversation_provider():
    provider = os.getenv("CONVERSATION_PROVIDER", "local").strip().lower()
    if provider not in {"elevenagents", "local"}:
        raise HTTPException(503, "Conversation provider is not configured correctly")
    return provider


def require_agent():
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "").strip()
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not agent_id or not api_key:
        raise HTTPException(503, "ElevenAgents credentials are not configured")
    if os.getenv("ACTIVE_CORPUS") == "licensed" and not licensed_context_allowed():
        raise HTTPException(503, "The licensed corpus is disabled for ElevenAgents")
    return agent_id, api_key


def available():
    try:
        require_agent()
        return True
    except HTTPException:
        return False


def licensed_context_allowed():
    return os.getenv("ELEVENLABS_ALLOW_LICENSED_CONTEXT") == "1"


def signed_session_url(agent_id: str, api_key: str) -> str:
    try:
        response = httpx.get(
            f"https://{AGENT_HOST}{AGENT_PATH}/get-signed-url",
            params={"agent_id": agent_id},
            headers={"xi-api-key": api_key},
            timeout=8,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        url = payload.get("signed_url") if isinstance(payload, dict) else None
        if isinstance(url, str) and len(url) <= 8192:
            target = urlsplit(url)
            params = parse_qs(target.query)
            if (
                target.scheme == "wss"
                and target.netloc == AGENT_HOST
                and target.path == AGENT_PATH
                and not target.fragment
                and params.get("agent_id") == [agent_id]
                and params.get("conversation_signature")
            ):
                return url
    except (httpx.HTTPError, ValueError):
        pass
    raise HTTPException(502, "ElevenAgents could not start the conversation")


def dataset_stories(db, story_ids):
    if licensed_context_allowed():
        return set()
    return set(
        db.scalars(
            select(StoryArticle.story_id)
            .join(Article, Article.id == StoryArticle.article_id)
            .join(IngestionJob, IngestionJob.id == Article.job_id)
            .where(StoryArticle.story_id.in_(story_ids), IngestionJob.kind == "dataset")
        )
    )


def context_sources(citations, excluded, allowed_articles=None):
    return [
        {
            "publisher": cite["source"][:180],
            "url": cite["url"],
            "excerpt": cite["excerpt"][:450],
            "synthetic": cite["is_synthetic"],
        }
        for cite in citations
        if cite["source_id"] not in excluded
        and (allowed_articles is None or cite["article_id"] in allowed_articles)
        and len(cite["url"]) <= 800
    ][:2]


def story_facts(db, story_ids, language, excluded, max_facts):
    withheld = dataset_stories(db, story_ids)
    for story_id in story_ids:
        if story_id in withheld:
            continue
        story = story_detail(db, story_id)
        if not story:
            continue
        languages = dict.fromkeys(
            [language, *(fact["language"] for fact in story["facts"])]
        )
        entries = (
            (fact, context_sources(cites, excluded))
            for lang in languages
            for fact, cites in service.eligible(
                story, lang, excluded, allow_conflict=True
            )
        )
        facts = [
            {
                "title": story["title"][:400],
                "published_at": story["event_at"],
                "text": fact["text"],
                "language": fact["language"],
                "status": fact["status"],
                "sources": sources,
            }
            for fact, sources in entries
            if sources
        ]
        yield from facts[:max_facts]


def episode_context(db, briefing, data, excluded):
    items = db.scalars(
        select(BriefingItem).where(BriefingItem.briefing_id == briefing.id)
    ).all()
    titles = {item.story_id: item.title for item in items}
    if data.story_id and data.story_id not in titles:
        raise HTTPException(422, "Story is outside this briefing")
    playback = min(data.playback_seconds, briefing.duration_seconds)
    withheld = dataset_stories(db, titles)
    segments = service.segments_for(db, briefing.id)
    if not segments:
        raise HTTPException(409, "Briefing context is not ready")
    article_ids = {
        cite["article_id"] for segment in segments for cite in segment.citations
    }
    article_query = select(Article.id).where(Article.id.in_(article_ids))
    if not licensed_context_allowed():
        article_query = article_query.join(IngestionJob).where(
            IngestionJob.kind != "dataset"
        )
    allowed = set(db.scalars(article_query))
    rows = []
    for segment in segments:
        if (
            segment.verification_status != "supported"
            or segment.story_id not in titles
            or segment.story_id in withheld
        ):
            continue
        sources = context_sources(segment.citations, excluded, allowed)
        if sources:
            rows.append(
                {
                    "title": titles[segment.story_id][:400],
                    "position": segment.position,
                    "start_seconds": segment.start_seconds,
                    "end_seconds": segment.end_seconds,
                    "text": segment.text,
                    "sources": sources,
                    "selected": bool(
                        data.story_id and segment.story_id == data.story_id
                    ),
                }
            )
    rows.sort(
        key=lambda row: (
            not row["selected"],
            not row["start_seconds"] <= playback < row["end_seconds"],
            max(row["start_seconds"] - playback, playback - row["end_seconds"], 0),
        )
    )
    focus = rows[0]["position"] if rows else None
    return (
        {
            "scope": "briefing",
            "title": briefing.title,
            "language": briefing.language,
            "playback_seconds": playback,
            "focus_position": focus,
        },
        rows,
    )


def context_for(db, user_id: str, data: AgentContextRequest) -> str:
    if data.conversation_id:
        from .models import Conversation
        conv = db.scalar(select(Conversation).where(Conversation.id == data.conversation_id, Conversation.user_id == user_id))
        if not conv:
            raise HTTPException(404, "Conversation not found")
        data = data.model_copy(update={"briefing_id": conv.briefing_id, "story_id": data.story_id or conv.story_id})
    prefs = preferences(db, user_id)
    excluded = set(prefs["excluded_sources"])
    language = prefs["language"]
    briefing = None
    if data.briefing_id:
        briefing = db.scalar(
            select(Briefing).where(
                Briefing.id == data.briefing_id, Briefing.user_id == user_id
            )
        )
        if not briefing:
            raise HTTPException(404, "Briefing not found")
    if briefing and not data.more_news:
        header, rows = episode_context(db, briefing, data, excluded)
    else:
        query = select(Story.id).where(Story.archived.is_(False))
        if data.story_id and not data.more_news:
            story_id = db.scalar(query.where(Story.id == data.story_id))
            if not story_id:
                raise HTTPException(404, "Story not found")
            header = {"scope": "story", "language": language}
            rows = story_facts(db, [story_id], language, excluded, max_facts=8)
        else:
            now = news_now()
            query = (
                query.where(Story.event_at.between(now - timedelta(days=1), now))
                .order_by(Story.event_at.desc(), Story.id)
                .limit(12)
            )
            if os.getenv("ACTIVE_CORPUS") == "licensed":
                query = query.where(Story.is_synthetic.is_(False))
            if briefing:
                previous_stories = select(BriefingItem.story_id).where(
                    BriefingItem.briefing_id == briefing.id
                )
                query = query.where(Story.id.not_in(previous_stories))
            header = {
                "scope": "more_news" if briefing else "latest_news",
                "language": briefing.language if briefing else language,
            }
            rows = story_facts(
                db, db.scalars(query).all(), language, excluded, max_facts=2
            )
    return pack_context(header, rows)


def pack_context(header, rows):
    context = {**header, "entries": [], "truncated": False}

    def render():
        return json.dumps(context, ensure_ascii=False, separators=(",", ":"))

    for row in rows:
        context["entries"].append(row)
        if len(render().encode()) > MAX_CONTEXT_BYTES:
            context["entries"].pop()
            context["truncated"] = True
    if header["scope"] == "briefing":
        context["entries"].sort(key=lambda row: row["position"])
    return render()
