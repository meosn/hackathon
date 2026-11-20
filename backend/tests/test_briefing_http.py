"""Exercise authenticated HTTP and WS with a real local worker and isolated storage."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from app import jobs
from app.accounts import seed_voices
from app.briefing import agent, routes
from app.config import settings
from app.db import get_db, load_models
from app.main import app
from app.news.service import import_fixture

V1 = "/api/v1"


@pytest.fixture
def api(tmp_path, monkeypatch):
    local_engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
        connect_args={"check_same_thread": False, "timeout": 20},
    )
    local_db = sessionmaker(local_engine, expire_on_commit=False)
    monkeypatch.setattr(jobs, "engine", local_engine)
    monkeypatch.setattr(jobs, "SessionLocal", local_db)
    monkeypatch.setattr(routes, "SessionLocal", local_db)
    monkeypatch.setattr(settings, "job_mode", "local")
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "rate_per_minute", 1000)
    monkeypatch.setattr(settings, "state_dir", tmp_path / "state")
    for name, val in {
        "AUDIO_STORAGE": "local",
        "AUDIO_DIR": str(tmp_path / "audio"),
        "TTS_PROVIDER": "local",
        "STT_PROVIDER": "mock",
        "CONVERSATION_PROVIDER": "local",
        "LLM_PROVIDER": "mock",
        "EMBEDDING_PROVIDER": "local_hash",
    }.items():
        monkeypatch.setenv(name, val)
    load_models().create_all(local_engine)
    with local_db.begin() as db:
        seed_voices(db)
        import_fixture(db)

    def dependency():
        with local_db() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    try:
        # Local tasks run in the actual background executor. The production scheduler is independent.
        yield TestClient(app, client=(tmp_path.name, 50000))
    finally:
        del app.dependency_overrides[get_db]
        local_engine.dispose()


def wait_for_edition(api, path, headers):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = api.get(path, headers=headers)
        assert result.status_code == 200
        data = result.json()
        if data["status"] in {"completed", "failed"}:
            return data
        time.sleep(0.05)
    pytest.fail("The local worker did not finish within 20 seconds")


def test_private_http_player_conversation_and_recovery(api):
    def profile(name):
        return api.post(V1 + "/auth/demo", json={"profile": name}).json()[
            "access_token"
        ]

    tech, finance = profile("tech"), profile("finance")
    headers, other = [{"Authorization": "Bearer " + t} for t in (tech, finance)]
    create = api.post(V1 + "/briefings", headers=headers, json={"period": "week"})
    assert create.status_code == 202 and create.json()["status"] == "queued"
    bid = create.json()["briefing_id"]
    path = f"{V1}/briefings/{bid}"
    with api.websocket_connect(f"{V1}/ws/briefings/{bid}") as socket:
        socket.send_json({"token": tech})
        for _ in range(10):
            message = socket.receive_json()
            assert message["briefing_id"] == bid and message["timestamp"]
            if message["status"] in {"failed", "completed"}:
                break
        assert message["event"] == "briefing.completed"
    with pytest.raises(WebSocketDisconnect) as denial:
        with api.websocket_connect(f"{V1}/ws/briefings/{bid}") as socket:
            socket.send_json({"token": finance})
            socket.receive_json()
    assert denial.value.code == 1008
    edition = api.get(path, headers=headers).json()
    segments = api.get(path + "/transcript", headers=headers).json()
    assert segments == edition["segments"]
    assert api.get(path + "/audio", headers=headers).content.startswith(b"RIFF")
    assert api.get(path + "/audio", headers=other).status_code == 404
    assert api.get(path + "/sources", headers=headers).json()
    assert api.get(path + "/sources", headers=other).status_code == 404
    assert api.get(path + "/audio").status_code == 401
    first_story = edition["items"][0]["story_id"]
    assert (
        api.put(V1 + "/listening-history/" + first_story, headers=headers).status_code
        == 204
    )
    assert (
        api.put(
            V1 + "/feedback/" + first_story, headers=headers, json={"score": 1}
        ).status_code
        == 204
    )
    assert (
        api.post(
            V1 + "/conversations", headers=other, json={"briefing_id": bid}
        ).status_code
        == 404
    )
    conversation = api.post(
        V1 + "/conversations", headers=headers, json={"briefing_id": bid}
    ).json()
    cpath = V1 + "/conversations/" + conversation["id"]
    answer = api.post(
        cpath + "/messages", headers=headers, json={"text": "Explain the second story."}
    ).json()
    assert answer["citations"] and answer["story_id"] == edition["items"][1]["story_id"]
    audio = f"{cpath}/messages/{answer['id']}/audio"
    assert api.get(audio, headers=headers).content.startswith(b"RIFF")
    assert api.get(audio, headers=other).status_code == 404
    rec = api.post(
        cpath + "/audio",
        headers=headers,
        files={"file": ("fixture.txt", b"Compare sources", "text/plain")},
    )
    assert rec.json()["transcription"] == "Compare sources" and rec.json()["citations"]
    assert len(api.get(cpath, headers=headers).json()["messages"]) == 4
    # Fail through the actual worker, adjust listener exclusions, retry the same edition ID.
    sources = [s["id"] for s in api.get(V1 + "/sources", headers=headers).json()]
    assert (
        api.put(
            V1 + "/users/me/sources",
            headers=headers,
            json={"excluded_sources": sources, "preferred_sources": []},
        ).status_code
        == 200
    )
    queued = api.post(
        V1 + "/briefings", headers=headers, json={"period": "week"}
    ).json()
    retry_path = V1 + "/briefings/" + queued["briefing_id"]
    failed = wait_for_edition(api, retry_path, headers)
    assert failed["status"] == "failed" and failed["error"]
    assert api.get(retry_path + "/audio", headers=headers).status_code == 409
    assert (
        api.put(
            V1 + "/users/me/sources",
            headers=headers,
            json={"excluded_sources": [], "preferred_sources": []},
        ).status_code
        == 200
    )
    assert api.post(retry_path + "/retry", headers=headers).status_code == 202
    assert wait_for_edition(api, retry_path, headers)["status"] == "completed"


def test_elevenagents_owns_context_and_issues_only_a_signed_url(api, monkeypatch):
    def profile(name):
        token = api.post(V1 + "/auth/demo", json={"profile": name}).json()[
            "access_token"
        ]
        return {"Authorization": "Bearer " + token}

    owner, other = profile("tech"), profile("finance")
    briefing = api.post(
        V1 + "/briefings", headers=owner, json={"period": "week", "story_limit": 1}
    ).json()["briefing_id"]
    detail = wait_for_edition(api, f"{V1}/briefings/{briefing}", owner)
    segment = next(segment for segment in detail["segments"] if segment["citations"])
    scope = {
        "briefing_id": briefing,
        "playback_seconds": segment["start_seconds"],
    }
    endpoint = V1 + "/agent-session"
    assert api.post(endpoint, headers=owner, json=scope).status_code == 503
    monkeypatch.setenv("CONVERSATION_PROVIDER", "elevenagents")
    monkeypatch.delenv("ELEVENLABS_AGENT_ID", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert api.get(V1 + "/health").json()["conversation_provider"] == "elevenagents"
    assert api.post(endpoint, headers=owner, json=scope).status_code == 503
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    signed = "wss://api.elevenlabs.io/v1/convai/conversation?agent_id=agent_test&conversation_signature=token"
    requested = []

    def request(url, *, params, headers, **kwargs):
        requested.append(url)
        assert params == {"agent_id": "agent_test"}
        assert headers == {"xi-api-key": "test-key"}
        return httpx.Response(
            200, json={"signed_url": signed}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(agent.httpx, "get", request)
    assert api.post(endpoint, json=scope).status_code == 401
    assert api.post(endpoint, headers=other, json=scope).status_code == 404
    assert (
        api.post(
            endpoint, headers=owner, json={**scope, "story_id": "unrelated"}
        ).status_code
        == 422
    )
    assert requested == []
    result = api.post(endpoint, headers=owner, json=scope)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert result.json()["signed_url"] == signed and "test-key" not in result.text
    context = json.loads(result.json()["context"])
    assert context["focus_position"] == segment["position"]
    entry = next(
        entry
        for entry in context["entries"]
        if entry["position"] == segment["position"]
    )
    assert entry["text"] == segment["text"]
    assert entry["sources"][0]["url"] == segment["citations"][0]["url"]
    assert entry["sources"][0]["excerpt"] == segment["citations"][0]["excerpt"][:450]
    refresh = api.post(V1 + "/agent-context", headers=owner, json=scope)
    assert refresh.json() == {"context": result.json()["context"]}
    extra = api.post(
        V1 + "/agent-context", headers=owner, json={**scope, "more_news": True}
    )
    extra_context = json.loads(extra.json()["context"])
    assert extra_context["scope"] == "more_news"
    assert not {entry["title"] for entry in extra_context["entries"]} & {
        item["title"] for item in detail["items"]
    }
    assert len(requested) == 1

    conv = api.post(
        V1 + "/conversations", headers=owner, json={"briefing_id": briefing}
    ).json()
    legacy = api.post(
        f"{V1}/conversations/{conv['id']}/audio",
        headers=owner,
        files={"file": ("test.wav", b"test", "audio/wav")},
    )
    assert legacy.status_code == 409
    monkeypatch.setenv("ACTIVE_CORPUS", "licensed")
    assert api.post(endpoint, headers=owner, json=scope).status_code == 503
    monkeypatch.setenv("ELEVENLABS_ALLOW_LICENSED_CONTEXT", "1")
    signed = signed.replace("api.elevenlabs.io", "other.example")
    blocked = api.post(endpoint, headers=owner, json=scope)
    assert blocked.status_code == 502 and "other.example" not in blocked.text


def test_daily_is_prepared_once_and_playback_never_regenerates(api):
    token = api.post(V1 + "/auth/demo", json={"profile": "tech"}).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    daily = api.post(V1 + "/briefings/daily", headers=headers).json()
    assert daily["voice_profile_id"] == "professional"
    again = api.post(V1 + "/briefings/daily", headers=headers).json()
    assert again["id"] == daily["id"]
    edition = wait_for_edition(api, V1 + "/briefings/" + daily["id"], headers)
    assert edition["status"] == "completed"
    assert api.get(
        V1 + "/briefings/" + daily["id"] + "/audio", headers=headers
    ).content.startswith(b"RIFF")
    api.patch(
        V1 + "/users/me/preferences",
        headers=headers,
        json={"voice_profile_id": "casual"},
    )
    same = api.post(V1 + "/briefings/daily", headers=headers).json()
    assert same["id"] == daily["id"] and same["voice_profile_id"] == "professional"
    custom = api.post(V1 + "/briefings", headers=headers, json={"period": "day"}).json()
    custom_edition = wait_for_edition(
        api, V1 + "/briefings/" + custom["briefing_id"], headers
    )
    assert custom_edition["voice_profile_id"] == "casual"
    assert custom_edition["id"] != daily["id"]
    conversation = api.post(
        V1 + "/conversations", headers=headers, json={"briefing_id": daily["id"]}
    ).json()
    message = api.post(
        V1 + "/conversations/" + conversation["id"] + "/messages",
        headers=headers,
        json={"text": "continue"},
    ).json()
    assert message["action"]["type"] == "RESUME_PLAYBACK"


def test_elevenlabs_scribe_transcription_contract(api, monkeypatch):
    import httpx
    from app.briefing import voice
    from app.db import SessionLocal

    monkeypatch.setenv("STT_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

    def server(request):
        assert request.url.path == "/v1/speech-to-text"
        assert request.headers["xi-api-key"] == "test-key"
        body = request.read()
        assert b"scribe_v2" in body and b"language_code" not in body
        return httpx.Response(200, json={"text": "What do other sources say?"})

    original = httpx.post

    def post(url, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(server)) as client:
            return client.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", post)
    token = api.post(V1 + "/auth/demo", json={"profile": "tech"}).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    conv = api.post(V1 + "/conversations", headers=headers, json={}).json()
    response = api.post(
        V1 + "/conversations/" + conv["id"] + "/audio",
        headers=headers,
        files={"file": ("question.webm", b"test-recording", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["transcription"] == "What do other sources say?"
    assert response.json()["citations"]
