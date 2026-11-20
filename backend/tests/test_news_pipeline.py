import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import admin_user, current_user
from app.db import Base, get_db, load_models
from app.news import adapters, analysis, service
from app.news.models import (
    Article,
    ArticleEmbedding,
    ClaimEvidence,
    IngestionJob,
    Story,
)
from app.news.routes import router
from app.usage import CostEvent, ModelUsage


@pytest.fixture()
def db(monkeypatch):
    # Default to offline deterministic vectors. An explicit provider exercises the same suite.
    monkeypatch.setenv(
        "EMBEDDING_PROVIDER", os.getenv("EMBEDDING_PROVIDER", "local_hash")
    )
    monkeypatch.setenv("CLUSTER_SIMILARITY", "0.46")
    load_models()
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_ingest_cluster_score_and_trace(db):
    first = service.import_fixture(db)
    assert (first.received, first.duplicates, first.analyzed) == (17, 1, 16)
    assert service.run_analysis(db, first.id).analyzed == 16
    assert service.import_fixture(db).id == first.id
    stats = service.stats(db)
    assert (stats["articles"], stats["stories"], stats["conflicting_claims"]) == (
        16,
        7,
        2,
    )
    assert len(db.scalars(select(ArticleEmbedding)).all()) == 16
    assert (
        len(db.scalars(select(ModelUsage).where(ModelUsage.stage == "embedding")).all())
        == 16
    )
    local_charges = db.scalars(
        select(CostEvent.measured_usd)
        .join(ModelUsage)
        .where(ModelUsage.scope == "dataset")
    ).all()
    assert len(local_charges) == 18 and all(charge == 0 for charge in local_charges)
    stories = service.story_list(db)
    tech = next(s for s in stories if "Aurora" in s["title"])
    assert set(tech["languages"]) == {"en", "nl"}
    assert "artificial_intelligence" in tech["topics"]
    assert len([s for s in stories if "Vela Labs" in s["title"]]) == 2
    assert max(stories, key=lambda s: s["urgency"])["category"] == "climate"
    assert next(s for s in stories if "Noren" in s["title"])["source_count"] == 2
    for s in stories:
        for f in service.story_detail(db, s["id"])["facts"]:
            citations = [e["article_id"] for e in f["evidence"]]
            assert citations
            assert service.verify_segment(db, f["text"], [f["id"]], citations) == (
                f["status"] == "supported"
            )
            for e in f["evidence"]:
                article = db.get(Article, e["article_id"])
                assert article.content[e["start"] : e["end"]] == e["excerpt"]
                assert article.url == e["url"]


def test_conflicting_claims_and_citation_tampering(db):
    service.import_fixture(db)
    story = next(s for s in service.story_list(db) if s["category"] == "energy")
    detail = service.story_detail(db, story["id"])
    assert len(detail["disagreements"]) == 1
    flagged = [
        f for f in detail["facts"] if f["id"] in detail["disagreements"][0]["fact_ids"]
    ]
    assert {tuple(analysis.tokens(f["text"])) for f in flagged}
    assert all(f["status"] == "conflicting" for f in flagged)
    assert any("40 megawatts" in f["text"] for f in flagged)
    assert any("42 megawatts" in f["text"] for f in flagged)
    fact = next(f for f in detail["facts"] if f["status"] == "supported")
    ids = [e["article_id"] for e in fact["evidence"]]
    assert not service.verify_segment(db, fact["text"], [fact["id"]], [])
    assert not service.verify_segment(db, fact["text"], [], ids)
    assert not service.verify_segment(
        db, fact["text"], [fact["id"]], ids + ["unrelated"]
    )
    ref = db.scalar(select(ClaimEvidence).where(ClaimEvidence.fact_id == fact["id"]))
    ref.start += 1
    assert not service.verify_segment(db, fact["text"], [fact["id"]], ids)


def test_duplicate_versions_and_newstex_adapter(db, tmp_path):
    def mk(id, hour, text):
        return dict(
            article_id=id,
            publisher="Example wire",
            headline="Oris opens Harbor transit pilot",
            body=text,
            original_url="https://publisher.example/" + id,
            language="en",
            publication_date=(
                datetime(2026, 11, 1, tzinfo=UTC) + timedelta(hours=hour)
            ).isoformat(),
        )

    body = (
        "Oris opened the Harbor transit pilot. The shuttle service starts at the eastern terminal. "
        "The timetable includes morning connections to the city centre. The operator released the schedule yesterday."
    )
    rows = [
        mk("1", 0, body),
        mk("copy", 1, "<p>" + body + "</p>"),
        mk("2", 1, body + " More details follow."),
        mk("3", 100, body.replace("morning", "evening")),
    ]
    path = tmp_path / "input.ndjson"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    job = service.ingest_file(db, path)
    assert (job.duplicates, job.analyzed) == (1, 3)
    assert service.stats(db)["near_duplicates"] == 1
    assert len(service.story_list(db)) == 2
    assert all(not s["is_synthetic"] for s in service.story_list(db))


def test_refuse_ambiguous_shared_entity_event():
    a = analysis.anchors("Vela Labs opens Aurora speech benchmark", "")
    assert not analysis.same_event(
        a, analysis.anchors("Vela Labs opens Meridian speech benchmark", ""), 0.99, 0.46
    )
    assert not analysis.same_event(
        a,
        analysis.anchors("Vela Labs publishes Aurora speech benchmark", ""),
        0.99,
        0.46,
    )


def test_dataset_allowlist_and_validation(tmp_path, monkeypatch):
    path = tmp_path / "week.json"
    path.write_text("[]")
    monkeypatch.setenv("DATASET_DIR", str(tmp_path))
    monkeypatch.setenv("DATASET_FILES", "week.json")
    assert adapters.dataset_path("week.json") == path
    for unsafe in ("../week.json", str(path), "missing.json", ""):
        with pytest.raises(ValueError):
            adapters.dataset_path(unsafe)
    with pytest.raises(ValueError):
        adapters.validate_feed("http://unconfigured.invalid/")
    assert (
        adapters.clean("<script>drop this</script><b>Arden opened</b> its pilot.")
        == "Arden opened its pilot."
    )


def test_api_pagination_filter_facts_and_admin_edits(db):
    service.import_fixture(db)
    db.commit()
    api = FastAPI()
    api.include_router(router, prefix="/api/v1")
    api.dependency_overrides[get_db] = lambda: db
    client = TestClient(api)
    assert client.get("/api/v1/stories").status_code == 401
    api.dependency_overrides[current_user] = lambda: type(
        "Listener", (), {"is_admin": False}
    )()

    def call(path, **kwargs):
        return client.get("/api/v1/" + path, **kwargs)

    first = call("stories", params={"limit": 2}).json()
    second = call("stories", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert not {v["id"] for v in first["items"]} & {v["id"] for v in second["items"]}
    assert call("stories", params={"cursor": "bad"}).status_code == 422
    assert call("stories", params={"topic": "finance", "language": "de"}).json()[
        "items"
    ]
    assert not call("stories", params={"search": "absent_term"}).json()["items"]
    story = call("stories", params={"topic": "energy"}).json()["items"][0]
    id = story["id"]
    articles = call(f"stories/{id}/articles").json()
    assert len(articles) == 2 and call(f"stories/{id}/source-comparison").json()
    assert call("articles/" + articles[0]["id"]).json()["content"]
    path = "/api/v1/stories/" + id + "/split"
    body = {"article_ids": [articles[0]["id"]]}
    assert client.post(path, json=body).status_code == 403
    api.dependency_overrides[admin_user] = lambda: True
    split = client.post(path, json=body)
    assert split.status_code == 200, split.text
    assert split.json()["article_count"] == 1 and not split.json()["disagreements"]
    merged = client.post(
        "/api/v1/stories/" + split.json()["id"] + "/merge", json={"into_story_id": id}
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["article_count"] == 2 and merged.json()["disagreements"]
