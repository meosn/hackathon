import json
import base64

import httpx

import pytest

from app.news.adapters import InputArticle
from app.news.grounding import supported_wording
from app.briefing.contracts import Answer, Entailment, Line
from app.briefing import discussion
from app.briefing.models import Conversation
from app.accounts import preferences
from app.news.service import story_detail, story_list
from app.news.models import Article
from app.news.routes import article_by_id
from app.news import service as news_service
from app.news.models import ArticleEmbedding
from app.briefing import voice
from sqlalchemy import select
from test_listener_workflow import session, listener
from test_news_pipeline import db


def test_newstex_publication_is_source_and_source_is_author():
    row = InputArticle.model_validate(
        {
            "$id": "test-1",
            "headline": "Oris opens a station",
            "text_content": "Oris opened a station.",
            "source": "A. Reporter",
            "publication": {"name": "Example Daily"},
            "permalink": "https://example.org/news/1",
            "date": "2026-11-19T08:00:00Z",
            "language": "en",
        }
    )
    assert row.source == "Example Daily"
    assert row.author == "A. Reporter"
    assert row.external_id == "test-1"


def test_licensed_article_endpoint_does_not_publish_full_text(session):
    article = session.scalar(select(Article).limit(1))
    article.is_synthetic = False
    result = article_by_id(session, article.id)
    assert result["content"] == ""
    assert result["full_text_available"] is False
    assert result["url"] == article.url


def test_crawler_rejects_unconfigured_urls(monkeypatch):
    from app.news.adapters import validate_crawl

    monkeypatch.setenv("CRAWL_URLS", "https://example.org/allowed")
    validate_crawl("https://example.org/allowed")
    with pytest.raises(ValueError):
        validate_crawl("https://example.org/other")
    with pytest.raises(ValueError):
        validate_crawl("http://127.0.0.1/private")


def test_archive_daily_edition_can_cover_available_week(session, monkeypatch):
    from app.briefing.daily import ensure_daily

    monkeypatch.setenv("DAILY_NEWS_PERIOD", "week")
    monkeypatch.setenv("NEWS_EDITION_VERSION", "archive-test")
    user = listener(session, "archive", "de", ["finance"])
    item = ensure_daily(session, user.id)
    assert item.request["period"] == "week"
    assert item.schedule_key.endswith("/archive-test")
    assert item.request["story_limit"] == 3


def test_daily_has_three_stories_and_more_news_excludes_previous_stories(
    session, monkeypatch
):
    from app.briefing.daily import ensure_daily
    from app.briefing.service import generate_script
    from app.briefing.models import BriefingItem

    monkeypatch.setenv("DAILY_NEWS_PERIOD", "week")
    user = listener(session, "top-three", "en", ["technology"])
    item = ensure_daily(session, user.id)
    generate_script(session, item.id)
    initial = set(
        session.scalars(
            select(BriefingItem.story_id).where(BriefingItem.briefing_id == item.id)
        )
    )
    assert len(initial) == 3
    conv = Conversation(user_id=user.id, briefing_id=item.id, language="en")
    session.add(conv)
    session.commit()
    first = discussion.respond(session, conv, "More news")
    second = discussion.respond(session, conv, "ещё новости")
    assert first.intent == second.intent == "GET_MORE_NEWS"
    added = set(first.action["story_ids"])
    assert added and not initial & added
    assert not (initial | added) & set(second.action["story_ids"])
    assert (
        discussion.classify(session, conv.id, "Give me more details").intent
        != "GET_MORE_NEWS"
    )


def test_aligned_speech_batches_preserve_segment_boundaries(session, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    parts = [("First sentence.", "en"), ("Second sentence.", "en")]
    joined = "\n\n".join(text for text, _ in parts)
    calls = []

    def synthesize(url, **kwargs):
        calls.append(kwargs["json"]["text"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "audio_base64": base64.b64encode(
                    voice.wav_bytes(b"\0\0" * voice.RATE * 2)
                ).decode(),
                "alignment": {
                    "characters": list(joined),
                    "character_start_times_seconds": [
                        i * 0.02 for i in range(len(joined))
                    ],
                },
            },
        )

    monkeypatch.setattr(voice.httpx, "post", synthesize)
    pcm, boundaries = voice.render_aligned(
        session, parts, ("elevenlabs", "test-model", "test-voice"), "test"
    )
    assert calls == [joined]
    assert len(boundaries) == 2 and boundaries[0][0] == 0
    assert boundaries[0][1] == boundaries[1][0]
    assert boundaries[-1][1] == pytest.approx(len(pcm) / (2 * voice.RATE))


def test_analysis_resumes_after_a_committed_batch(db, monkeypatch):
    from app.news.models import IngestionJob

    monkeypatch.setenv("ANALYSIS_BATCH_SIZE", "2")
    job = news_service.create_job(db)
    news_service.run_ingestion(db, job.id)
    job_id = job.id
    analyze = news_service._analyze
    attempts = []

    def interrupted(session, article):
        attempts.append(article.id)
        if len(attempts) == 3:
            raise RuntimeError("Interrupted after one batch")
        return analyze(session, article)

    monkeypatch.setattr(news_service, "_analyze", interrupted)
    with pytest.raises(RuntimeError):
        news_service.run_analysis(db, job_id)
    db.rollback()
    assert db.get(IngestionJob, job_id).analyzed == 2
    monkeypatch.setattr(news_service, "_analyze", analyze)
    assert news_service.run_analysis(db, job_id).analyzed == 16
    assert len(db.scalars(select(ArticleEmbedding)).all()) == 16


def test_numeric_changes_never_reach_semantic_reviewer(session, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "api")

    def unexpected(*args):
        pytest.fail("A changed number must fail deterministic validation")

    monkeypatch.setattr("app.briefing.providers.model_output", unexpected)
    assert not supported_wording(session, "Revenue rose 40%.", "Revenue rose 4%.", "x")


def test_paraphrase_requires_source_entailment(session, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "api")
    calls = []

    def review(db, reference, messages, schema):
        calls.append(messages)
        assert schema is Entailment
        return Entailment(supported=True)

    monkeypatch.setattr("app.briefing.providers.model_output", review)
    assert supported_wording(
        session, "A station was opened by Oris.", "Oris opened a station.", "x"
    )
    assert len(calls) == 1


def test_semantic_reviewer_can_reject_changed_negation(session, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "api")
    monkeypatch.setattr(
        "app.briefing.providers.model_output", lambda *args: Entailment(supported=False)
    )
    assert not supported_wording(
        session, "Oris did not open a station.", "Oris opened a station.", "x"
    )


def test_generated_answer_receives_history_and_validates_ids(session, monkeypatch):
    user = listener(session, "rag", "en", ["technology"])
    story = story_detail(
        session, next(s["id"] for s in story_list(session) if "Aurora" in s["title"])
    )
    conv = Conversation(user_id=user.id, story_id=story["id"], language="en")
    session.add(conv)
    session.commit()
    discussion.respond(session, conv, "Give me more details")
    fact = next(
        f
        for f in story["facts"]
        if f["language"] == "en" and f["status"] == "supported"
    )

    def generate(db, reference, messages, schema):
        payload = json.loads(messages[-1]["content"])
        assert len(payload["history"]) == 2
        assert payload["evidence"] and payload["question"] == "And what happened next?"
        return Answer(
            lines=[Line(story_id=story["id"], claim_id=fact["id"], text=fact["text"])]
        )

    monkeypatch.setattr(discussion, "model_output", generate)
    text, citations = discussion.generated_answer(
        session,
        conv,
        story,
        "And what happened next?",
        preferences(session, user.id),
        "FOLLOW_UP",
    )
    assert text == fact["text"] and citations
    monkeypatch.setattr(
        discussion,
        "model_output",
        lambda *args: Answer(
            lines=[Line(story_id="unrelated", claim_id=fact["id"], text=fact["text"])]
        ),
    )
    with pytest.raises(ValueError, match="outside"):
        discussion.generated_answer(
            session,
            conv,
            story,
            "And what happened next?",
            preferences(session, user.id),
            "FOLLOW_UP",
        )
