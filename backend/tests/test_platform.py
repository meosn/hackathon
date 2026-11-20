import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.accounts import Schedule, User, demo_listener, seed_voices
from app.config import settings
from app.db import get_db, load_models
from app.jobs import discover
from app.main import app
from app.messaging import Receipt, consume
from app.usage import costs, record


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(settings, "job_mode", "local")
    monkeypatch.setattr(settings, "demo_mode", True)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    load_models().create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        seed_voices(db)
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c
    del app.dependency_overrides[get_db]


def test_migrate_bootstrap_and_repeat(tmp_path):
    env = {
        **os.environ,
        "DATABASE_URL": "sqlite:///" + str(tmp_path / "test.db"),
        "DEMO_MODE": "true",
        "JOB_MODE": "local",
        "AUDIO_STORAGE": "local",
        "EMBEDDING_PROVIDER": "local_hash",
    }
    base = Path(__file__).resolve().parents[1]
    for _ in range(2):
        r = subprocess.run(
            [sys.executable, "-m", "app.cli", "bootstrap"],
            cwd=base,
            env=env,
            check=True,
            capture_output=True,
        )
        assert b'"received": 17' in r.stdout
    from alembic.config import Config
    from sqlalchemy import inspect

    engine = create_engine(env["DATABASE_URL"])
    assert set(load_models().tables).issubset(inspect(engine).get_table_names())


def test_private_accounts_authorization_and_schedule(client):
    def headers(token):
        return {"Authorization": "Bearer " + token}

    registration = {
        "email": "reader@example.org",
        "name": "Reader",
        "password": "test-only-secret",
    }
    assert client.get("/api/v1/users/me").status_code == 401
    token = client.post("/api/v1/auth/register", json=registration).json()[
        "access_token"
    ]
    h = headers(token)
    assert client.post("/api/v1/auth/register", json=registration).status_code == 409
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": registration["email"], "password": "wrong"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={k: registration[k] for k in ("email", "password")},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/metrics/costs", headers=h).status_code == 403
    assert (
        client.post(
            "/api/v1/ingestion/jobs", headers=h, json={"kind": "fixture"}
        ).status_code
        == 403
    )
    assert client.patch(
        "/api/v1/users/me/preferences", headers=h, json={"interests": ["custom"]}
    ).json()["interests"] == ["custom"]
    s = client.post(
        "/api/v1/schedules",
        json={"time": "08:30", "timezone": "Europe/Amsterdam"},
        headers=h,
    ).json()
    assert s["id"] and s["enabled"]
    assert (
        client.patch(
            "/api/v1/schedules/" + s["id"], json={"timezone": "Unknown/Zone"}, headers=h
        ).status_code
        == 422
    )
    b = client.post("/api/v1/auth/demo", json={"profile": "finance"}).json()[
        "access_token"
    ]
    assert (
        client.delete("/api/v1/schedules/" + s["id"], headers=headers(b)).status_code
        == 404
    )
    assert client.get("/api/v1/schedules", headers=headers(b)).json() == []
    assert client.delete("/api/v1/schedules/" + s["id"], headers=h).status_code == 204


def test_scheduler_fall_back_is_once_per_local_day(session):
    from app.briefing.models import Briefing

    u = demo_listener(session, "tech")
    s = Schedule(user_id=u.id, time="02:00", timezone="Europe/Amsterdam", enabled=True)
    session.add(s)
    session.commit()
    for hour in (0, 1, 2):
        discover(session, datetime(2026, 10, 25, hour, 30, tzinfo=timezone.utc))
    assert session.scalar(select(func.count()).select_from(Briefing)) == 1


def test_event_replay_and_cost_scaling(session):
    payload = dict(
        version=1,
        event_id="e-1",
        entity_id="a-1",
        correlation_id="c-1",
        routing_key="news.article.created",
        timestamp="2026-01-01T00:00:00Z",
    )
    consume(session, payload)
    consume(session, payload)
    assert session.scalar(select(func.count()).select_from(Receipt)) == 1
    with pytest.raises(ValueError):
        consume(session, payload | {"version": 2})
    record(session, "embedding", "test", scope="dataset", measured_usd=2)
    record(session, "tts", "test", scope="listener", characters=100, estimated_usd=3)
    session.commit()
    result = costs(session)
    assert result["measured_usd"] == 2 and result["estimated_usd"] == 3
    assert result["projected_10x_usd"] == 23


def test_discussion_model_preference_persists_and_uses_evidence_rules(
    client, session, monkeypatch
):
    from app.briefing.discussion import classify
    from app.briefing.models import Conversation
    from app import accounts

    result = client.post("/api/v1/auth/demo", json={"profile": "tech"})
    headers = {"Authorization": "Bearer " + result.json()["access_token"]}
    models = client.get("/api/v1/assistant/models", headers=headers).json()
    assert {m["id"] for m in models} == {"grounded", "configured"}
    assert (
        client.patch(
            "/api/v1/users/me/preferences",
            headers=headers,
            json={"discussion_model": "grounded"},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/users/me/preferences", headers=headers).json()[
            "discussion_model"
        ]
        == "grounded"
    )
    assert (
        client.patch(
            "/api/v1/users/me/preferences",
            headers=headers,
            json={"discussion_model": "arbitrary-code"},
        ).status_code
        == 422
    )
    uid = client.get("/api/v1/users/me", headers=headers).json()["id"]
    conv = Conversation(user_id=uid, language="en")
    session.add(conv)
    session.commit()

    def unexpected_provider(*args):
        pytest.fail("The source-search selection should use evidence rules")

    monkeypatch.setattr("app.briefing.discussion.model_output", unexpected_provider)
    assert (
        classify(session, conv.id, "What changed in this announcement?").intent
        == "FOLLOW_UP"
    )
    assert (
        classify(session, conv.id, "What do other sources say?").intent
        == "COMPARE_SOURCES"
    )
