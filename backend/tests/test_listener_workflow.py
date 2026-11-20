import io
from datetime import UTC, datetime
from types import SimpleNamespace
import wave

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.accounts import User, seed_voices, set_preferences
from app.briefing import discussion, service, voice
from app.briefing.contracts import BriefingRequest, Script
from app.briefing.models import BriefingSegment, Conversation, GeneratedAudio
from app.briefing.ranking import ranked
from app.db import load_models
from app.news.service import import_fixture, story_detail, story_list
from app.usage import ModelUsage


@pytest.fixture
def session(tmp_path, monkeypatch):
    for key, value in {
        "AUDIO_STORAGE": "local",
        "AUDIO_DIR": str(tmp_path / "audio"),
        "TTS_PROVIDER": "local",
        "LLM_PROVIDER": "mock",
        "STT_PROVIDER": "mock",
        "EMBEDDING_PROVIDER": "local_hash",
    }.items():
        monkeypatch.setenv(key, value)
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    load_models().create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        seed_voices(db)
        import_fixture(db)
        db.commit()
        yield db
    engine.dispose()


def listener(db, name, lang, interests):
    user = User(name=name, email=f"{name}@example.test", password_hash="test-hash")
    db.add(user)
    db.flush()
    set_preferences(db, user.id, {"interests": interests, "language": lang})
    db.commit()
    return user


def test_listeners_audio_boundaries_and_cache(session):
    db = session
    results = {}
    for lang, interest in [("en", "technology"), ("de", "finance")]:
        user = listener(db, lang, lang, [interest])
        item = service.create_briefing(db, user.id, BriefingRequest(period="week"))
        assert item.status == "queued"
        assert service.generate_script(db, item.id) == "script_ready"
        assert service.synthesize_briefing(db, item.id) == "completed"
        result = service.briefing_view(db, item, True)
        results[lang] = result["items"][0]["story_id"]
        assert all(s["language"] == lang for s in result["segments"])
        assert result["audio_provider"] == "local"
        for segment in result["segments"]:
            assert segment["end_seconds"] > segment["start_seconds"]
            if segment["verification_status"] == "supported":
                assert segment["claim_ids"] and segment["citations"][0]["url"]
                assert segment["text"] in [c["excerpt"] for c in segment["citations"]]
        audio = db.get(GeneratedAudio, item.audio_id)
        with wave.open(io.BytesIO(voice.read_object(audio.object_key)), "rb") as wav:
            assert wav.getframerate() == 22050
            assert wav.getnframes() / 22050 == pytest.approx(result["duration_seconds"])
            assert any(wav.readframes(wav.getnframes()))
        count_before = db.scalar(
            select(func.count())
            .select_from(ModelUsage)
            .where(ModelUsage.stage == "tts")
        )
        another = service.create_briefing(db, user.id, BriefingRequest(period="week"))
        service.generate_script(db, another.id)
        service.synthesize_briefing(db, another.id)
        assert another.audio_id == item.audio_id
        assert service.synthesize_briefing(db, another.id) == "completed"
        assert count_before == db.scalar(
            select(func.count())
            .select_from(ModelUsage)
            .where(ModelUsage.stage == "tts")
        )
    assert results["en"] != results["de"]


def test_hallucination_blocks_publication(session, monkeypatch):
    user = listener(session, "listener", "en", ["technology"])
    item = service.create_briefing(session, user.id, BriefingRequest())
    real = service.model_output

    def injected(*args):
        result = real(*args)
        result.lines[0].text = "The price doubled to 800 million dollars."
        return result

    monkeypatch.setattr(service, "model_output", injected)
    with pytest.raises(service.VerificationError):
        service.generate_script(session, item.id)
    assert not item.audio_id
    assert session.scalar(select(func.count()).select_from(BriefingSegment)) == 0


def test_final_reverification_before_synthesis(session):
    user = listener(session, "listener", "en", [])
    item = service.create_briefing(session, user.id, BriefingRequest())
    service.generate_script(session, item.id)
    rows = service.segments_for(session, item.id)
    next(
        row for row in rows if row.claim_ids
    ).text += " The company doubled its earnings."
    session.commit()
    with pytest.raises(service.VerificationError):
        service.synthesize_briefing(session, item.id)
    assert not item.audio_id


def test_source_exclusion_and_unsupported_language(session):
    user = listener(session, "listener", "en", [])
    story = story_list(session)[0]
    set_preferences(session, user.id, {"excluded_sources": story["source_ids"]})
    item = service.create_briefing(
        session, user.id, BriefingRequest(selected_story_ids=[story["id"]])
    )
    with pytest.raises(service.VerificationError):
        service.generate_script(session, item.id)


def test_rank_guards_and_unheard():
    now = datetime(2026, 11, 20, tzinfo=UTC)
    base = {
        "event_at": now.isoformat(),
        "topics": ["technology"],
        "category": "technology",
        "source_ids": ["a"],
        "importance": 0.7,
        "urgency": 0.2,
    }
    pool = [base | {"id": str(i)} for i in range(5)] + [
        base
        | {
            "id": "breaking",
            "topics": ["world"],
            "category": "world",
            "urgency": 0.95,
            "importance": 0.82,
        }
    ]
    pref = {"interests": ["technology"]}
    rank = ranked(pool, pref, heard={"0"}, now=now)
    assert [s["id"] for s in rank[:3]] == ["1", "2", "breaking"]
    assert rank[-1]["id"] == "0"
    assert len(ranked(pool, {"interests": ["archaeology"]}, now=now)) == 6
    assert ranked(pool, pref | {"excluded_sources": ["a"]}, now=now) == []
    assert ranked(pool, pref, selected=["4"], now=now)[0]["id"] == "4"


def test_conversation_retrieval_and_controls(session):
    user = listener(session, "listener", "en", ["technology"])
    item = service.create_briefing(session, user.id, BriefingRequest())
    service.generate_script(session, item.id)
    ids = [i["story_id"] for i in service.briefing_view(session, item, True)["items"]]
    conv = Conversation(user_id=user.id, briefing_id=item.id, language="en")
    session.add(conv)
    session.commit()
    select_reply = discussion.respond(session, conv, "Explain the second story")
    assert select_reply.story_id == ids[1] and select_reply.citations
    assert discussion.respond(session, conv, "What do the sources say?").citations
    assert (
        discussion.respond(session, conv, "How many unicorns are on Saturn?").citations
        == []
    )
    assert (
        discussion.respond(session, conv, "Switch to the casual voice").action[
            "voice_profile_id"
        ]
        == "casual"
    )
    assert discussion.respond(session, conv, "Stop playback").intent == "STOP_PLAYBACK"
    news = discussion.respond(session, conv, "Tell me about AI")
    assert news.intent == "FILTER_TOPIC" and news.citations
    assert all("https://" in c["url"] for c in news.citations)
    weekly = discussion.respond(session, conv, "What happened this week?")
    assert weekly.intent == "GET_PERIOD_NEWS" and len(weekly.citations) > 1


def test_conflicts_are_attributed(session):
    user = listener(session, "listener", "en", [])
    story = next(
        detail
        for s in story_list(session)
        if (detail := story_detail(session, s["id"]))["disagreements"]
    )
    conv = Conversation(user_id=user.id, story_id=story["id"], language="en")
    session.add(conv)
    session.commit()
    answer = discussion.respond(session, conv, "Compare sources")
    assert "disagree" in answer.text
    assert len({c["source"] for c in answer.citations}) >= 2


def test_voice_fallback_and_recording_fixture(session, monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "permitted-voice")

    def network_failure(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx, "post", network_failure)
    audio = voice.render_audio(
        session,
        [SimpleNamespace(text="Thank you for listening.", language="en")],
        "professional",
        "test",
    )
    assert audio.provider == "local"
    assert (
        voice.transcribe(session, b"Compare sources", "text/plain", "en", "test")
        == "Compare sources"
    )
    with pytest.raises(ValueError, match="Whisper"):
        voice.transcribe(session, b"not speech", "audio/webm", "en", "test")


def test_citation_snapshot_must_match_the_database(session):
    user = listener(session, "listener", "en", [])
    item = service.create_briefing(session, user.id, BriefingRequest())
    service.generate_script(session, item.id)
    line = next(row for row in service.segments_for(session, item.id) if row.claim_ids)
    line.citations = [
        c | {"url": "https://example.invalid/wrong-article"} for c in line.citations
    ]
    session.commit()
    with pytest.raises(service.VerificationError):
        service.synthesize_briefing(session, item.id)
    assert not item.audio_id


@pytest.mark.parametrize("kind", ["api", "ollama"])
def test_structured_provider_wire_contract(session, monkeypatch, kind):
    """Controlled HTTP transport checks both remote schemas and recorded usage."""
    import json
    from app.briefing.providers import model_output

    monkeypatch.setenv("LLM_PROVIDER", kind)
    monkeypatch.setenv(
        "LLM_BASE_URL",
        "https://model.example/v1" if kind == "api" else "http://ollama.example",
    )
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-token")
    line = {"story_id": "s", "claim_id": "c", "text": "The approved source text."}
    content = json.dumps({"lines": [line]})

    def server(request):
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        if kind == "ollama":
            assert request.url.path == "/api/chat"
            assert "lines" in body["format"]["properties"]
            data = {
                "message": {"content": content},
                "prompt_eval_count": 19,
                "eval_count": 8,
            }
        else:
            assert request.url.path == "/v1/chat/completions"
            assert (
                "lines"
                in body["response_format"]["json_schema"]["schema"]["properties"]
            )
            assert request.headers["Authorization"] == "Bearer test-token"
            data = {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 19, "completion_tokens": 8},
            }
        return httpx.Response(200, json=data)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(server), **kwargs),
    )
    actual = model_output(
        session, "test", [{"role": "user", "content": "approved data"}], Script
    )
    assert actual.lines[0].model_dump() == line
    row = session.scalars(select(ModelUsage).where(ModelUsage.stage == "llm")).one()
    assert (row.input_tokens, row.output_tokens) == (19, 8)


def test_whisper_and_elevenlabs_wire_contracts(session, monkeypatch):
    """Exercise multipart upload and actual audio decoding with simulated remote responses."""
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-tts")
    monkeypatch.setenv("ELEVENLABS_VOICE_MAP", '{"professional":"licensed-test-voice"}')
    monkeypatch.setenv("STT_PROVIDER", "whisper")
    monkeypatch.setenv("STT_BASE_URL", "https://whisper.example/v1")
    monkeypatch.setenv("STT_API_KEY", "test-stt")
    recording = voice.wav_bytes(
        voice.local_pcm("Compare sources.", "en", "professional")
    )

    def response(url, **kwargs):
        request = httpx.Request("POST", url)
        if url.endswith("/audio/transcriptions"):
            assert kwargs["headers"]["Authorization"] == "Bearer test-stt"
            assert kwargs["files"]["file"] == ("recording.wav", recording, "audio/wav")
            return httpx.Response(
                200, request=request, json={"text": "Compare sources."}
            )
        assert url.endswith("/v1/text-to-speech/licensed-test-voice")
        assert kwargs["headers"]["xi-api-key"] == "test-tts"
        assert kwargs["json"]["text"] == "Compare sources."
        return httpx.Response(200, request=request, content=recording)

    monkeypatch.setattr(httpx, "post", response)
    assert (
        voice.transcribe(session, recording, "audio/wav", "en", "conv")
        == "Compare sources."
    )
    result = voice.render_audio(
        session,
        [SimpleNamespace(text="Compare sources.", language="en")],
        "professional",
        "conv",
    )
    assert result.provider == "elevenlabs" and result.duration_seconds > 0
    assert voice.read_object(result.object_key).startswith(b"RIFF")


def test_followup_uses_the_actual_spoken_digest_order(session):
    user = listener(session, "wildcard", "en", ["flood_warning"])
    conv = Conversation(user_id=user.id, language="en")
    session.add(conv)
    session.commit()
    edition = discussion.respond(session, conv, "What happened this week?")
    assert len(edition.action["story_ids"]) == 3
    set_preferences(session, user.id, {"interests": ["finance"]})
    assert (
        discussion.respond(session, conv, "Explain the second story").story_id
        == edition.action["story_ids"][1]
    )
    assert discussion.respond(session, conv, "Explain the fourth story").citations == []


def test_named_followup_leaves_current_story_with_matching_evidence(session):
    user = listener(session, "reader", "en", ["technology"])
    current = next(s for s in story_list(session) if "Aurora" in s["title"])
    conv = Conversation(user_id=user.id, story_id=current["id"], language="en")
    session.add(conv)
    session.commit()
    result = discussion.respond(session, conv, "What rate did Maren Bank set?")
    assert result.story_id != current["id"] and "2.5%" in result.text
    assert result.citations and all("2.5%" in c["excerpt"] for c in result.citations)
    followup = discussion.respond(
        session, conv, "How many languages does the Aurora benchmark include?"
    )
    assert followup.story_id == current["id"] and "24 languages" in followup.text


def test_rejected_remote_wording_is_replaced_and_usage_is_retained(
    session, monkeypatch
):
    import json
    from app.usage import CostEvent

    user = listener(session, "reader", "en", ["technology"])
    monkeypatch.setenv("LLM_PROVIDER", "api")
    monkeypatch.setenv("LLM_MODEL", "contract-model")
    monkeypatch.setenv("LLM_INPUT_USD_PER_M", "2")
    attempts = []

    def server(request):
        data = json.loads(request.content)
        lines = json.loads(data["messages"][-1]["content"])
        if not attempts:
            lines[0]["text"] = "This unsupported claim costs 400 million dollars."
        attempts.append(True)
        content = json.dumps({"lines": lines})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 20},
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(server), **kwargs),
    )
    item = service.create_briefing(session, user.id, BriefingRequest())
    assert service.generate_script(session, item.id) == "script_ready"
    calls = session.scalars(
        select(ModelUsage).where(
            ModelUsage.stage == "llm", ModelUsage.reference_id == item.id
        )
    ).all()
    assert len(calls) == 1 and calls[0].input_tokens == 1000
    charge = session.scalars(
        select(CostEvent).where(CostEvent.usage_id == calls[0].id)
    ).one()
    assert charge.estimated_usd == pytest.approx(0.002) and charge.measured_usd is None
    assert item.audio_id is None
    assert item.request["source_wording_claim_ids"]
    assert all(
        "400 million" not in s.text for s in service.segments_for(session, item.id)
    )
    assert service.generate_script(session, item.id) == "script_ready"
    assert service.generate_script(session, item.id) == "script_ready"
    calls = session.scalars(
        select(ModelUsage).where(
            ModelUsage.stage == "llm", ModelUsage.reference_id == item.id
        )
    ).all()
    assert len(calls) == len(attempts) == 1
    assert sum(c.input_tokens for c in calls) == 1000


def test_daily_calendar_idempotence_and_prepared_profile_copy(session):
    from datetime import datetime, timedelta, timezone
    from app.accounts import demo_listener, set_preferences, User
    from app.briefing.daily import ensure_daily, seed_templates
    from app.briefing.models import Briefing, BriefingItem

    seed_templates(session)
    source = session.scalar(
        select(User).where(User.email == "daily-tech@system.invalid")
    )
    prepared = ensure_daily(session, source.id)
    session.commit()
    service.generate_script(session, prepared.id)
    service.synthesize_briefing(session, prepared.id)
    user = demo_listener(session, "tech")
    session.commit()
    copy = ensure_daily(session, user.id)
    session.commit()
    assert copy.status == "completed" and copy.audio_id == prepared.audio_id
    assert copy.id != prepared.id
    assert session.scalar(
        select(BriefingItem.id).where(BriefingItem.briefing_id == copy.id)
    )
    assert ensure_daily(session, user.id).id == copy.id
    tomorrow = ensure_daily(
        session, user.id, datetime.now(timezone.utc) + timedelta(days=1)
    )
    assert tomorrow.id != copy.id
