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


def test_revoice_is_private_and_runs_only_narration(api, monkeypatch):
    from app.briefing import service

    token = api.post(V1 + "/auth/demo", json={"profile": "tech"}).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    result = api.post(
        V1 + "/briefings",
        headers=headers,
        json={"period": "week", "story_limit": 3, "duration_minutes": 1},
    )
    path = V1 + "/briefings/" + result.json()["briefing_id"]
    source = wait_for_edition(api, path, headers)
    assert source["status"] == "completed"
    other_token = api.post(V1 + "/auth/demo", json={"profile": "finance"}).json()[
        "access_token"
    ]
    assert (
        api.post(
            path + "/revoice", headers={"Authorization": "Bearer " + other_token}
        ).status_code
        == 404
    )

    def unexpected(*args):
        pytest.fail("A revoice request must skip script generation")

    monkeypatch.setattr(service, "generate_script", unexpected)
    assert (
        api.patch(
            V1 + "/users/me/preferences",
            headers=headers,
            json={"voice_profile_id": "energetic"},
        ).status_code
        == 200
    )
    result = api.post(path + "/revoice", headers=headers)
    assert result.status_code == 202
    item = wait_for_edition(
        api, V1 + "/briefings/" + result.json()["briefing_id"], headers
    )
    assert item["status"] == "completed"
    assert item["voice_profile_id"] == "energetic"
    assert item["items"] == source["items"]
    assert [s["text"] for s in item["segments"]] == [
        s["text"] for s in source["segments"]
    ]


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
        json={"voice_profile_id": "jarvis"},
    )
    same = api.post(V1 + "/briefings/daily", headers=headers).json()
    assert same["id"] != daily["id"] and same["voice_profile_id"] == "jarvis"
    assert [row["text"] for row in same["segments"]] == [row["text"] for row in edition["segments"]]
    custom = api.post(V1 + "/briefings", headers=headers, json={"period": "day"}).json()
    custom_edition = wait_for_edition(
        api, V1 + "/briefings/" + custom["briefing_id"], headers
    )
    assert custom_edition["voice_profile_id"] == "jarvis"
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


def test_realtime_session_is_private_and_evidence_uses_no_text_model(api, monkeypatch):
    from app.briefing import realtime, discussion
    import httpx
    import json

    headers = {
        "Authorization": "Bearer "
        + api.post(V1 + "/auth/demo", json={"profile": "tech"}).json()["access_token"]
    }
    other = {
        "Authorization": "Bearer "
        + api.post(V1 + "/auth/demo", json={"profile": "finance"}).json()[
            "access_token"
        ]
    }
    conv = api.post(V1 + "/conversations", headers=headers).json()
    path = V1 + "/conversations/" + conv["id"]
    sdp = "v=0\r\ns=test-only-sdp-offer\r\n"
    assert (
        api.post(path + "/realtime", headers=other, json={"sdp": sdp}).status_code
        == 404
    )
    monkeypatch.setenv("REALTIME_ENABLED", "1")
    monkeypatch.setenv("LLM_API_KEY", "private-test-key")
    requests = []

    def exchange(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(
            201, text="v=0\r\ns=provider-answer\r\n", request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(realtime.httpx, "post", exchange)
    result = api.post(path + "/realtime", headers=headers, json={"sdp": sdp})
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("application/sdp")
    assert "private-test-key" not in result.text
    config = json.loads(requests[0][1]["files"]["session"][1])
    assert config["output_modalities"] == ["audio"]
    assert config["max_output_tokens"] >= 2000
    assert config["audio"]["input"]["turn_detection"]["type"] == "server_vad"
    assert config["audio"]["input"]["turn_detection"]["silence_duration_ms"] == 450

    def unexpected(*args, **kwargs):
        raise AssertionError("Evidence must not invoke a text model")

    monkeypatch.setattr(discussion, "model_output", unexpected)
    payload = {
        "question": "Ещё новости",
        "decision": {"intent": "GET_MORE_NEWS", "period": "week"},
    }
    first = api.post(path + "/realtime-evidence", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json()["citations"]
    assert first.json()["action"]["story_ids"]
    second = api.post(path + "/realtime-evidence", headers=headers, json=payload)
    assert not set(first.json()["action"]["story_ids"]) & set(
        second.json()["action"]["story_ids"]
    )
    selected = first.json()["action"]["story_ids"][0]
    followup = api.post(
        path + "/realtime-evidence",
        headers=headers,
        json={
            "question": "Explain this story",
            "decision": {"intent": "EXPLAIN_STORY"},
            "story_id": selected,
        },
    )
    assert followup.status_code == 200
    assert followup.json()["story_id"] == selected
    payload["story_id"] = "outside-this-briefing"
    assert (
        api.post(path + "/realtime-evidence", headers=headers, json=payload).status_code
        == 422
    )


def test_custom_live_voice_validates_audio_and_stays_with_its_owner(api, monkeypatch):
    import io
    import wave

    from app.briefing import custom_voice

    def listener(name):
        result = api.post(
            V1 + "/auth/register",
            json={
                "email": f"{name}@example.org",
                "name": name,
                "password": "test-password",
            },
        )
        assert result.status_code == 201
        return {"Authorization": "Bearer " + result.json()["access_token"]}

    def sample(seconds):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(bytes(seconds * 8000 * 2))
        return {"file": ("sample.wav", buffer.getvalue(), "audio/wav")}

    monkeypatch.setenv("CONVERSATION_PROVIDER", "elevenagents")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent_test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    owner, other = listener("owner"), listener("other")
    created = []

    def clone(key, audio, name="Custom"):
        assert key == "test-key"
        assert audio.startswith(b"RIFF")
        created.append(True)
        return "owner-voice-id"

    monkeypatch.setattr(custom_voice, "clone_voice", clone)
    monkeypatch.setattr(
        agent, "signed_session_url", lambda *_: "wss://example.org/signed"
    )
    path = V1 + "/users/me/custom-voice"
    assert (
        api.post(
            path, headers=owner, data={"consent": "false"}, files=sample(30)
        ).status_code
        == 422
    )
    for seconds in (1, 9):
        assert (
            api.post(
                path, headers=owner, data={"consent": "true"}, files=sample(seconds)
            ).status_code
            == 422
        )
    assert created == []
    monkeypatch.setenv("CONVERSATION_PROVIDER", "local")
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    result = api.post(path, headers=owner, data={"consent": "true"}, files=sample(30))
    assert result.status_code == 201, result.text
    assert result.json()["sample_uploaded"] is True
    assert result.json()["saved"] is False
    assert result.json()["can_create"] is False
    assert api.get(path, headers=other).json()["sample_uploaded"] is False
    assert created == []
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    assert api.post(path + "/create", headers=other).status_code == 404
    result = api.post(path + "/create", headers=owner)
    assert result.status_code == 200
    assert result.json()["active"] is True
    assert result.json()["sample_uploaded"] is False
    assert api.get(path, headers=other).json()["saved"] is False
    assert (
        api.post(V1 + "/agent-session", headers=other, json={}).json()["voice_id"]
        == "onwK4e9ZLuTAKqWW03F9"
    )
    assert (
        api.post(V1 + "/agent-session", headers=owner, json={}).json()["voice_id"]
        == "owner-voice-id"
    )
    assert api.patch(path, headers=owner, json={"active": False}).json()["saved"]
    assert (
        api.post(V1 + "/agent-session", headers=owner, json={}).json()["voice_id"]
        == "onwK4e9ZLuTAKqWW03F9"
    )
    edited = api.patch(path, headers=owner, json={"name": "My private host", "persona": "Warm, unhurried delivery."})
    assert edited.json()["name"] == "My private host"
    assert api.get(path, headers=other).json()["name"] == "Custom"
    assert api.get(path, headers=owner).json()["persona"] == "Warm, unhurried delivery."
    assert created == [True]
    assert api.get(V1 + "/users/me/preferences", headers=owner).json()["voice_engine"] == "elevenlabs"
    assert api.get(V1 + "/users/me/preferences", headers=other).json()["voice_engine"] == "elevenlabs"


def test_streamed_speech_token_is_private_and_uses_the_selected_voice(api, monkeypatch):
    import json
    import httpx
    from app.briefing import conversation_speech, realtime

    token = api.post(V1 + "/auth/demo", json={"profile": "tech"}).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    other = {
        "Authorization": "Bearer "
        + api.post(V1 + "/auth/demo", json={"profile": "finance"}).json()[
            "access_token"
        ]
    }
    conv = api.post(V1 + "/conversations", headers=headers).json()
    path = V1 + "/conversations/" + conv["id"] + "/speech-session"
    monkeypatch.setenv("REALTIME_SPEECH_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "server-private-key")
    monkeypatch.setenv(
        "ELEVENLABS_VOICE_MAP",
        json.dumps({"professional": "voice-a", "jarvis": "voice-b"}),
    )
    calls = []

    def authorize(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(
            200,
            json={"token": "single-use-authorization"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(conversation_speech.httpx, "post", authorize)
    assert api.post(path, headers=other).status_code == 404
    assert calls == []
    result = api.post(path, headers=headers)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "private, no-store"
    assert result.json()["token"] == "single-use-authorization"
    assert result.json()["voice_id"] == "voice-a"
    assert "server-private-key" not in result.text
    assert calls[0][1]["headers"]["xi-api-key"] == "server-private-key"
    assert realtime.session_config("en", [])["output_modalities"] == ["text"]
    assert realtime.session_config("en", [], speech_stream=False)[
        "output_modalities"
    ] == ["audio"]
    api.patch(
        V1 + "/users/me/preferences",
        headers=headers,
        json={"voice_profile_id": "jarvis"},
    )
    assert api.post(path, headers=headers).json()["voice_id"] == "voice-b"


def test_voice_engines_and_database_characters_are_private_per_listener(api, monkeypatch):
    from app.accounts import VoiceProfile
    from sqlalchemy import select
    from app.briefing import realtime

    def listener():
        token = api.post(V1 + '/auth/demo', json={'profile': 'tech'}).json()['access_token']
        return {'Authorization': 'Bearer ' + token}

    owner, other = listener(), listener()
    monkeypatch.setenv('ELEVENLABS_AGENT_ID', 'agent_test')
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-key')
    monkeypatch.setenv('REALTIME_ENABLED', '1')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-openai')
    monkeypatch.setenv('ELEVENLABS_ALLOW_LICENSED_CONTEXT', '1')
    monkeypatch.setattr(agent, 'signed_session_url', lambda *_: 'wss://api.elevenlabs.io/signed')
    options = api.get(V1 + '/voice-engines', headers=owner)
    assert options.status_code == 200
    assert {row['id'] for row in options.json() if row['available']} == {'openai', 'elevenlabs'}
    assert api.get(V1 + '/voice-engines').status_code == 401
    path = V1 + '/users/me/preferences'
    assert api.patch(path, headers=owner, json={'voice_profile_id': 'gangsta'}).status_code == 403
    with routes.SessionLocal() as db:
        from app.accounts import User
        user_id = api.get(V1 + '/users/me', headers=owner).json()['id']
        db.get(User, user_id).is_premium = True
        db.commit()
    chosen = api.patch(path, headers=owner, json={'voice_engine': 'elevenlabs', 'voice_profile_id': 'gangsta'})
    assert chosen.json()['voice_engine'] == 'elevenlabs'
    assert api.get(path, headers=other).json()['voice_engine'] == 'elevenlabs'
    assert api.patch(path, headers=other, json={'voice_engine': 'invalid'}).status_code == 422

    with routes.SessionLocal.begin() as db:
        character = db.scalar(select(VoiceProfile).where(VoiceProfile.slug == 'gangsta'))
        assert character.elevenlabs_voice_id == 'N2lVS1w4EtoT3dr4eOWO'
        assert character.openai_voice == 'ash'
        character.elevenlabs_voice_id = 'saved-shared-character'
    selected = api.post(V1 + '/agent-session', headers=owner, json={}).json()
    assert selected['voice_id'] == 'saved-shared-character'
    assert 'West Coast' in selected['persona']
    assert api.post(V1 + '/agent-session', headers=other, json={}).json()['voice_id'] == 'onwK4e9ZLuTAKqWW03F9'

    conv = api.post(V1 + '/conversations', headers=owner, json={}).json()['id']
    assert api.post(V1 + '/agent-session', headers=other, json={'conversation_id': conv}).status_code == 404
    exchanged = []
    def exchange(url, **kwargs):
        config = json.loads(kwargs['files']['session'][1])
        exchanged.append(config)
        return httpx.Response(201, text='answer-sdp', request=httpx.Request('POST', url))
    monkeypatch.setattr(realtime.httpx, 'post', exchange)
    result = api.post(f'{V1}/conversations/{conv}/realtime', headers=owner, json={'sdp': 'v=0\r\n' + 'a=test\r\n' * 4, 'speech_stream': False})
    assert result.status_code == 200
    assert result.headers['x-speech-output'] == 'openai'
    assert exchanged[0]['output_modalities'] == ['audio']
    assert exchanged[0]['audio']['output']['voice'] == 'ash'
    assert 'West Coast' in exchanged[0]['instructions']


def test_agent_can_resume_additional_news_after_switching_provider(api, monkeypatch):
    token = api.post(V1 + '/auth/demo', json={'profile': 'tech'}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    bid = api.post(V1 + '/briefings', headers=headers, json={'period': 'week', 'story_limit': 1}).json()['briefing_id']
    edition = wait_for_edition(api, f'{V1}/briefings/{bid}', headers)
    conv = api.post(V1 + '/conversations', headers=headers, json={'briefing_id': bid}).json()['id']
    more = api.post(f'{V1}/conversations/{conv}/realtime-evidence', headers=headers,
                    json={'question': 'More news', 'decision': {'intent': 'GET_MORE_NEWS'}})
    assert more.status_code == 200
    current = more.json()['story_id']
    assert current not in {item['story_id'] for item in edition['items']}
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-key')
    monkeypatch.setenv('ELEVENLABS_AGENT_ID', 'agent-test')
    monkeypatch.setenv('CONVERSATION_PROVIDER', 'elevenagents')
    monkeypatch.setattr(agent, 'signed_session_url', lambda *_: 'wss://api.elevenlabs.io/signed')
    result = api.post(V1 + '/agent-session', headers=headers, json={'conversation_id': conv})
    assert result.status_code == 200, result.text
    context = json.loads(result.json()['context'])
    assert context['scope'] == 'story'
    assert {entry['story_id'] for entry in context['entries']} == {current}
    assert api.post(V1 + '/agent-context', headers=headers,
                    json={'conversation_id': conv, 'story_id': 'unrelated'}).status_code == 422


def test_ponald_drump_preset_uses_the_voice_created_from_the_reference(api, monkeypatch):
    token = api.post(V1 + '/auth/demo', json={'profile': 'tech'}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    catalog = api.get(V1 + '/voices', headers=headers).json()
    character = next(row for row in catalog if row['id'] == 'energetic')
    assert character['name'] == 'Ponald Drump'
    assert 'recording' in character['description']
    changed = api.patch(V1 + '/users/me/preferences', headers=headers,
                        json={'voice_profile_id': 'energetic', 'voice_engine': 'elevenlabs'})
    assert changed.status_code == 200
    monkeypatch.setenv('ELEVENLABS_AGENT_ID', 'agent_test')
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-key')
    monkeypatch.setattr(agent, 'signed_session_url', lambda *_: 'wss://api.elevenlabs.io/signed')
    session = api.post(V1 + '/agent-session', headers=headers, json={})
    assert session.status_code == 200
    assert session.json()['voice_id'] == 'CBtIsr4irOknVyIz3EzI'
    assert 'AI news narrator' in session.json()['persona']
