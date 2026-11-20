import io
import wave

import httpx
import pytest
from sqlalchemy import select
from fastapi import HTTPException

from app.accounts import VoiceProfile, set_preferences
from app.briefing import preview, voice
from test_listener_workflow import session, listener
from test_briefing_http import api


def test_samples_use_selected_engine_voice_and_cache_each_language(
    session, monkeypatch
):
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("OPENAI_API_KEY", "server-openai-key")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "server-eleven-key")
    monkeypatch.setattr(voice, "convert_audio", lambda content: b"\x01\0" * voice.RATE)
    calls = []

    def speech(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(
            200, request=httpx.Request("POST", url), content=b"encoded-speech"
        )

    monkeypatch.setattr(voice.httpx, "post", speech)
    user = listener(session, "samples", "en", ["technology"])
    first = preview.render(
        session, user, "professional", preview.PreviewRequest(engine="openai")
    )
    again = preview.render(
        session, user, "professional", preview.PreviewRequest(engine="openai")
    )
    assert first.id == again.id and len(calls) == 1
    assert calls[0][0] == "https://api.openai.com/v1/audio/speech"
    assert calls[0][1]["json"]["voice"] == "marin"
    assert calls[0][1]["json"]["input"] == preview.PHRASES["en"]
    other = preview.render(
        session, user, "professional", preview.PreviewRequest(engine="elevenlabs")
    )
    assert first.id != other.id
    assert calls[1][0].endswith("/onwK4e9ZLuTAKqWW03F9")
    assert calls[1][1]["json"]["text"] == preview.PHRASES["en"]
    preview.render(
        session,
        user,
        "professional",
        preview.PreviewRequest(engine="elevenlabs", language="de"),
    )
    assert len(calls) == 3 and calls[2][1]["json"]["text"] == preview.PHRASES["de"]


def test_custom_previews_are_resolved_per_owner_and_change_after_recloning(
    session, monkeypatch
):
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "server-eleven-key")
    monkeypatch.setattr(voice, "convert_audio", lambda content: b"\x01\0" * voice.RATE)
    ids = []

    def speech(url, **kwargs):
        ids.append(url.rsplit("/", 1)[-1])
        return httpx.Response(
            200, request=httpx.Request("POST", url), content=b"speech"
        )

    monkeypatch.setattr(voice.httpx, "post", speech)
    first = listener(session, "first-sample", "en", [])
    second = listener(session, "second-sample", "en", [])
    first.custom_voice_id, second.custom_voice_id = "private-one", "private-two"
    request = preview.PreviewRequest(engine="elevenlabs")
    a, b = [
        preview.render(session, owner, "custom", request) for owner in (first, second)
    ]
    assert a.id != b.id and ids == ["private-one", "private-two"]
    first.custom_voice_id = "private-new"
    new = preview.render(session, first, "custom", request)
    assert new.id != a.id and ids[-1] == "private-new"
    with pytest.raises(HTTPException):
        preview.render(
            session, first, "custom", preview.PreviewRequest(engine="openai")
        )


def test_retired_voice_cannot_be_selected_even_if_historical_profile_remains(session):
    user = listener(session, "retired-voice", "en", [])
    session.add(
        VoiceProfile(
            slug="casual", name="Street Signal", description="Historical preset"
        )
    )
    session.flush()
    with pytest.raises(HTTPException):
        set_preferences(session, user.id, {"voice_profile_id": "casual"})
    with pytest.raises(HTTPException) as rejected:
        preview.render(session, user, "casual", preview.PreviewRequest())
    assert rejected.value.status_code == 404


def test_preview_http_returns_audio_and_never_accepts_arbitrary_text_or_voice_ids(api):
    token = api.post("/api/v1/auth/demo", json={"profile": "tech"}).json()[
        "access_token"
    ]
    headers = {"Authorization": "Bearer " + token}
    path = "/api/v1/voices/professional/preview"
    assert api.post(path).status_code == 401
    assert "casual" not in [
        item["id"] for item in api.get("/api/v1/voices", headers=headers).json()
    ]
    assert api.post("/api/v1/voices/casual/preview", headers=headers).status_code == 404
    assert api.post("/api/v1/voices/custom/preview", headers=headers).status_code == 404
    assert (
        api.post(path, headers=headers, json={"text": "Arbitrary text"}).status_code
        == 422
    )
    result = api.post(
        path, headers=headers, json={"engine": "openai", "language": "en"}
    )
    assert (
        result.status_code == 200
        and result.headers["cache-control"] == "private, no-store"
    )
    assert result.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(result.content), "rb") as media:
        assert media.getnframes() > 0
        assert any(media.readframes(media.getnframes()))


def test_retirement_migration_moves_preferences_and_preserves_historical_episodes(
    session,
):
    from pathlib import Path
    import runpy
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.accounts import UserPreference
    from app.briefing.models import Briefing

    user = listener(session, "legacy-street", "en", [])
    session.add(
        VoiceProfile(
            slug="casual", name="Street Signal", description="Historical preset"
        )
    )
    session.flush()
    pref = session.scalar(
        select(UserPreference).where(UserPreference.user_id == user.id)
    )
    pref.voice_profile_id = "casual"
    old = Briefing(
        user_id=user.id,
        title="Saved episode",
        language="en",
        voice_profile_id="casual",
        request={"period": "day"},
        status="completed",
    )
    session.add(old)
    session.commit()
    migration = (
        Path(__file__).parents[1] / "alembic/versions/0008_retire_street_signal.py"
    )
    with Operations.context(MigrationContext.configure(session.connection())):
        runpy.run_path(str(migration))["upgrade"]()
    session.expire_all()
    assert pref.voice_profile_id == "professional"
    assert old.voice_profile_id == "casual"
    assert session.scalar(select(VoiceProfile).where(VoiceProfile.slug == "casual"))
