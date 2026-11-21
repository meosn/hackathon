from datetime import datetime, UTC
from hashlib import sha256
from array import array
from sqlalchemy import select
import pytest
from app.accounts import User
from app.briefing.learning import topic_affinities
from app.briefing.models import UserFeedback
from app.briefing.ranking import ranked
from app.briefing.voice import RATE, trim_long_pauses
from app.news.coverage import coverage
from app.news.models import (
    Story,
    StoryArticle,
    Source,
    Article,
    Fact,
    ClaimEvidence,
    IngestionJob,
    SourceDisagreement,
)
from test_listener_workflow import session, listener
from test_briefing_http import api


def test_custom_topic_library_survives_deselection_and_is_private(api):
    def auth():
        return {
            "Authorization": "Bearer "
            + api.post("/api/v1/auth/demo", json={"profile": "tech"}).json()[
                "access_token"
            ]
        }

    first, other = auth(), auth()
    p = "/api/v1/users/me/preferences"
    result = api.patch(
        p,
        headers=first,
        json={"custom_topics": ["Space Law"], "interests": ["Space Law"]},
    )
    assert result.status_code == 200 and result.json()["custom_topics"] == ["space_law"]
    result = api.patch(p, headers=first, json={"interests": []})
    assert result.json()["interests"] == [] and result.json()["custom_topics"] == [
        "space_law"
    ]
    assert api.get(p, headers=first).json()["custom_topics"] == ["space_law"]
    assert api.get(p, headers=other).json()["custom_topics"] == []
    assert (
        api.patch(p, headers=first, json={"custom_topics": []}).json()["custom_topics"]
        == []
    )
    story = api.get("/api/v1/stories", headers=first).json()["items"][0]["id"]
    feedback = "/api/v1/feedback/" + story
    assert api.get(feedback).status_code == 401
    assert api.put(feedback, headers=first, json={"score": 1}).status_code == 204
    assert api.get(feedback, headers=first).json()["score"] == 1
    assert api.get(feedback, headers=other).json()["score"] == 0


def make_story(db, category="politics"):
    now = datetime.now(UTC)
    row = Story(
        title="A separate reported event",
        summary="Source context",
        category=category,
        importance=0.5,
        urgency=0.1,
        event_at=now,
        updated_at=now,
        is_synthetic=True,
    )
    db.add(row)
    db.flush()
    return row


def test_reaction_generalizes_to_other_political_news_without_affecting_other_listener(
    session,
):
    a, b = listener(session, "a", "en", ["finance"]), listener(
        session, "b", "en", ["finance"]
    )
    liked = make_story(session)
    signal = UserFeedback(user_id=a.id, story_id=liked.id, score=1)
    session.add(signal)
    session.commit()
    learned = topic_affinities(session, a.id)
    assert learned["politics"] > 0.9 and topic_affinities(session, b.id) == {}
    now = datetime.now(UTC)
    stories = [
        dict(
            id=str(i),
            title="Market update",
            summary="",
            category="finance" if i < 3 else "politics",
            topics=[],
            source_ids=["publisher"],
            event_at=now,
            importance=0.5,
            urgency=0.1,
        )
        for i in range(4)
    ]
    prefs = {"interests": ["finance"]}
    assert "3" not in [s["id"] for s in ranked(stories, prefs, now=now)[:3]]
    assert "3" in [
        s["id"] for s in ranked(stories, prefs, affinities=learned, now=now)[:3]
    ]
    signal.score = -1
    session.commit()
    assert topic_affinities(session, a.id)["politics"] < -0.9
    signal.score = 0
    session.commit()
    assert topic_affinities(session, a.id) == {}


def test_translations_and_reprints_do_not_count_as_independent_corroboration(session):
    story = make_story(session)
    fact = Fact(
        story_id=story.id,
        text="The council approved a new transport plan.",
        language="en",
        status="supported",
    )
    session.add(fact)
    session.flush()
    job = session.scalar(select(IngestionJob))

    def report(name, duplicate=None):
        src = Source(name=name, is_synthetic=True)
        session.add(src)
        session.flush()
        body = fact.text + " Additional editorial context from " + name + "."
        article = Article(
            source_id=src.id,
            job_id=job.id,
            title=story.title,
            content=body,
            url="https://example.test/" + src.id,
            published_at=story.event_at,
            language="en",
            content_hash=sha256(body.encode()).hexdigest(),
            is_synthetic=True,
            near_duplicate_of=duplicate,
            status="analyzed",
        )
        session.add(article)
        session.flush()
        session.add_all(
            [
                StoryArticle(story_id=story.id, article_id=article.id),
                ClaimEvidence(
                    fact_id=fact.id,
                    article_id=article.id,
                    excerpt=fact.text,
                    start=0,
                    end=len(fact.text),
                ),
            ]
        )
        session.flush()
        return src, article

    _, original = report("Invezz")
    report("Invezz - German")
    report("Syndicated Daily", original.id)
    assert coverage(session, [story.id])[story.id]["publisher_count"] == 1
    independent, article = report("Independent Observer")
    info = coverage(session, [story.id])[story.id]
    assert (
        info["publisher_count"] == 2
        and info["corroborated_claim_count"] == 1
        and info["coverage_status"] == "corroborated"
    )
    assert (
        coverage(session, [story.id], [independent.id])[story.id]["coverage_status"]
        == "single_source"
    )
    article.content = "Changed original source."
    session.flush()
    assert (
        coverage(session, [story.id])[story.id]["coverage_status"] == "multiple_reports"
    )
    session.add(
        SourceDisagreement(
            story_id=story.id,
            description="Conflicting reported plans.",
            fact_ids=[fact.id],
        )
    )
    session.flush()
    assert coverage(session, [story.id])[story.id]["coverage_status"] == "conflicting"


def test_trump_pause_trimming_keeps_all_voiced_samples_and_updates_timestamps():
    voiced = array("h", [1500] * round(0.4 * RATE)).tobytes()
    pcm = (
        voiced
        + b"\0\0" * round(0.95 * RATE)
        + voiced
        + b"\0\0" * round(0.3 * RATE)
        + voiced
    )
    result, cues = trim_long_pauses(pcm, [[0, 1.35], [1.35, len(pcm) / (2 * RATE)]])
    assert len(result) / (2 * RATE) == pytest.approx(
        len(pcm) / (2 * RATE) - 0.6, abs=0.02
    )
    assert cues[1][0] == pytest.approx(0.75, abs=0.02)
    assert cues[-1][1] == pytest.approx(len(result) / (2 * RATE), abs=0.001)
    values = array("h")
    values.frombytes(result)
    assert sum(v == 1500 for v in values) == round(0.4 * RATE) * 3


def test_topic_migration_preserves_existing_custom_selections():
    import json
    import runpy
    from pathlib import Path
    from sqlalchemy import create_engine
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE user_preferences (user_id TEXT PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE user_interests (user_id TEXT, topic TEXT)")
        db.exec_driver_sql("CREATE TABLE story_topics (name TEXT)")
        db.exec_driver_sql("CREATE TABLE stories (category TEXT)")
        db.exec_driver_sql("INSERT INTO user_preferences VALUES ('owner')")
        db.exec_driver_sql(
            "INSERT INTO user_interests VALUES ('owner','politics'),('owner','space_law')"
        )
        db.exec_driver_sql("INSERT INTO stories VALUES ('politics')")
        path = Path(__file__).parents[1] / "alembic/versions/0010_custom_topics.py"
        with Operations.context(MigrationContext.configure(db)):
            runpy.run_path(str(path))["upgrade"]()
        assert json.loads(
            db.exec_driver_sql("SELECT custom_topics FROM user_preferences").scalar()
        ) == ["space_law"]
    engine.dispose()
