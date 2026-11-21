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
    assert {m["id"] for m in models} == {"grounded", "configured", "local"}
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


def test_weekly_schedule_is_atomic_private_and_preserves_completed_slots(client, session, monkeypatch):
    from app import account_routes
    fixed = datetime(2026, 11, 23, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(account_routes, 'utcnow', lambda: fixed)
    token = client.post('/api/v1/auth/demo', json={'profile': 'tech'}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    rows = [
        {'time': '08:00', 'timezone': 'Europe/Berlin', 'days_of_week': [0, 2], 'enabled': True},
        {'time': '18:30', 'timezone': 'Europe/Berlin', 'days_of_week': [0], 'enabled': True},
    ]
    result = client.put('/api/v1/schedules', json=rows, headers=headers)
    assert result.status_code == 200, result.text
    ids = [row['id'] for row in result.json()]
    first = session.get(Schedule, ids[0])
    first.last_local_date = fixed.date()
    session.commit()
    repeated = client.put('/api/v1/schedules', json=rows, headers=headers)
    assert [row['id'] for row in repeated.json()] == ids
    assert session.get(Schedule, ids[0]).last_local_date == fixed.date()
    for invalid in [
        [{**rows[0], 'days_of_week': []}],
        [{**rows[0], 'days_of_week': [7]}],
        [{**rows[0], 'days_of_week': ['0']}],
        [{**rows[0], 'timezone': 'Mars/Unknown'}],
        [rows[0], {**rows[0], 'days_of_week': [2]}],
    ]:
        assert client.put('/api/v1/schedules', json=invalid, headers=headers).status_code == 422
        assert [row['id'] for row in client.get('/api/v1/schedules', headers=headers).json()] == ids
    other = client.post('/api/v1/auth/demo', json={'profile': 'finance'}).json()['access_token']
    assert client.get('/api/v1/schedules', headers={'Authorization': 'Bearer '+other}).json() == []
    zones = client.get('/api/v1/timezones', headers=headers).json()
    assert {'GMT+00:00', 'GMT+02:00', 'GMT-05:00', 'GMT+05:45'} <= set(zones)
    assert all(zone.startswith('GMT') for zone in zones)
    assert client.get('/api/v1/timezones').status_code == 401
    # Saving during the selected minute must still dispatch today's delivery.
    current = client.put('/api/v1/schedules', json=[{**rows[0], 'time': '07:00'}], headers=headers).json()[0]
    assert session.get(Schedule, current['id']).last_local_date is None
    # A newly added past slot waits for its next occurrence; it does not replay today.
    past = client.put('/api/v1/schedules', json=[{**rows[0], 'time': '01:00'}], headers=headers).json()[0]
    assert session.get(Schedule, past['id']).last_local_date == fixed.date()


def test_scheduler_creates_separate_weekday_editions_for_each_delivery(session):
    from app.briefing.models import Briefing
    user = demo_listener(session, 'tech')
    for time, days in [('08:00', [0]), ('18:00', [0]), ('09:00', [2])]:
        session.add(Schedule(user_id=user.id, time=time, timezone='Europe/Berlin', days_of_week=days, enabled=True))
    session.commit()
    count = lambda: session.scalar(select(func.count()).select_from(Briefing))
    for date, hour, minute, expected in [
        (22, 20, 0, 0),  # Sunday, no delivery.
        (23, 6, 59, 0),  # Monday, before 08:00 Berlin.
        (23, 7, 0, 1),
        (23, 7, 15, 1),  # Repeated discovery is idempotent.
        (23, 17, 0, 2),
        (24, 20, 0, 2),  # Tuesday is disabled.
        (25, 8, 0, 3),
    ]:
        discover(session, datetime(2026, 11, date, hour, minute, tzinfo=timezone.utc))
        assert count() == expected
    keys = session.scalars(select(Briefing.schedule_key)).all()
    assert len(set(keys)) == 3
    assert all(key.startswith('scheduled/') for key in keys)


def test_schedule_weekday_uses_the_delivery_zone_across_midnight(session):
    from app.briefing.models import Briefing
    user = demo_listener(session, 'tech')
    session.add(Schedule(user_id=user.id, time='08:00', timezone='Pacific/Kiritimati', days_of_week=[0], enabled=True))
    session.commit()
    # Sunday in UTC is already Monday morning in this delivery zone.
    discover(session, datetime(2026, 11, 22, 18, tzinfo=timezone.utc))
    row = session.scalar(select(Briefing))
    assert '/2026-11-23/08:00/' in row.schedule_key


def test_fixed_gmt_offsets_validate_and_drive_delivery_and_daily_dates(session, client):
    from app.timezones import resolve_timezone, timezone_name
    from app.briefing.models import Briefing
    from app.briefing.daily import ensure_daily
    from app.accounts import set_preferences
    user = demo_listener(session, 'tech')
    set_preferences(session, user.id, {'timezone': 'GMT+5:45'})
    assert timezone_name('GMT+5:45') == 'GMT+05:45'
    assert resolve_timezone('GMT-03:30').utcoffset(None).total_seconds() == -12600
    for invalid in ['GMT+14:15', 'GMT-12:30', 'GMT+2:60', 'GMT+99', 'GMT+NaN']:
        with pytest.raises(ValueError):
            timezone_name(invalid)
    session.add(Schedule(user_id=user.id, time='08:17', timezone='GMT+05:45', days_of_week=[0], enabled=True))
    session.commit()
    discover(session, datetime(2026, 11, 23, 2, 31, tzinfo=timezone.utc))
    assert session.scalar(select(func.count()).select_from(Briefing)) == 0
    discover(session, datetime(2026, 11, 23, 2, 32, tzinfo=timezone.utc))
    assert session.scalar(select(func.count()).select_from(Briefing)) == 1
    discover(session, datetime(2026, 11, 23, 2, 33, tzinfo=timezone.utc))
    assert session.scalar(select(func.count()).select_from(Briefing)) == 1
    # The baseline also uses the fixed offset when UTC and local dates differ.
    edition = ensure_daily(session, user.id, datetime(2026, 11, 22, 20, tzinfo=timezone.utc))
    assert '/2026-11-23/top3' in edition.schedule_key
    token = client.post('/api/v1/auth/demo', json={'profile': 'tech'}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    patched = client.patch('/api/v1/users/me/preferences', headers=headers, json={'timezone': 'GMT-3:30'})
    assert patched.status_code == 200
    assert patched.json()['timezone'] == 'GMT-03:30'
    saved = client.put('/api/v1/schedules', headers=headers,
                       json=[{'time': '09:17', 'timezone': 'GMT+5:45', 'days_of_week': [0]}])
    assert saved.status_code == 200, saved.text
    assert saved.json()[0]['timezone'] == 'GMT+05:45'


def test_guest_is_private_resumable_and_can_upgrade_without_losing_preferences(client, session):
    def enter(data={}):
        response = client.post('/api/v1/auth/guest', json=data)
        assert response.status_code == 200
        return response.json()['access_token']
    first = enter()
    headers = {'Authorization': 'Bearer ' + first}
    original = client.get('/api/v1/auth/me', headers=headers).json()
    assert original['is_guest'] and not original['is_demo']
    other = enter()
    assert client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer ' + other}).json()['id'] != original['id']
    client.patch('/api/v1/users/me/preferences', headers=headers, json={'duration_minutes': 3})
    resumed = enter({'guest_token': first})
    assert client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer ' + resumed}).json()['id'] == original['id']
    upgraded = client.post('/api/v1/auth/register', json={'email': 'upgrade@example.com', 'name': 'Listener', 'password': 'long-password', 'guest_token': first})
    assert upgraded.status_code == 201, upgraded.text
    personal = {'Authorization': 'Bearer ' + upgraded.json()['access_token']}
    me = client.get('/api/v1/auth/me', headers=personal).json()
    assert me['id'] == original['id'] and not me['is_guest']
    assert client.get('/api/v1/users/me/preferences', headers=personal).json()['duration_minutes'] == 3
    assert client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer ' + enter({'guest_token': first})}).json()['id'] != original['id']


def test_google_login_verified_identity_and_guest_upgrade(client, session, monkeypatch):
    from app import google_auth
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'test.apps.googleusercontent.com')
    assert client.get('/api/v1/auth/providers').json()['google_client_id'] == 'test.apps.googleusercontent.com'
    monkeypatch.setattr(google_auth, 'verify', lambda *args: {'sub': 'google-unique', 'email': 'hello@gmail.com', 'name': 'Google Listener'})
    guest = client.post('/api/v1/auth/guest', json={}).json()['access_token']
    before = client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer '+guest}).json()
    body = {'credential': 'x'*30, 'nonce': 'n'*32, 'guest_token': guest}
    response = client.post('/api/v1/auth/google', json=body)
    assert response.status_code == 200, response.text
    user = client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer '+response.json()['access_token']}).json()
    assert user['id'] == before['id'] and not user['is_guest']
    again = client.post('/api/v1/auth/google', json={**body, 'guest_token': None})
    assert client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer '+again.json()['access_token']}).json()['id'] == user['id']


def test_google_validates_signature_audience_expiry_issuer_and_nonce(monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from types import SimpleNamespace
    from app import google_auth
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'test-client')
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(google_auth.keys, 'get_signing_key_from_jwt', lambda _: SimpleNamespace(key=private.public_key()))
    from app.db import utcnow
    from datetime import timedelta
    claims = {'iss':'https://accounts.google.com','aud':'test-client','sub':'123','email':'test@gmail.com','email_verified':True,'nonce':'nonce','iat':utcnow(),'exp':utcnow()+timedelta(minutes=5)}
    encode = lambda c, key=private: jwt.encode(c, key, algorithm='RS256')
    assert google_auth.verify(encode(claims), 'nonce')['sub'] == '123'
    for changes in [{'aud':'other'}, {'iss':'attacker'}, {'exp':utcnow()-timedelta(minutes=1)}, {'nonce':'other'}, {'email_verified':False}]:
        with pytest.raises(Exception) as error:
            google_auth.verify(encode({**claims, **changes}), 'nonce')
        assert error.value.status_code == 401
    with pytest.raises(Exception) as error:
        google_auth.verify(encode(claims, rsa.generate_private_key(public_exponent=65537,key_size=2048)), 'nonce')
    assert error.value.status_code == 401
