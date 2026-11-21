import base64
import io
import wave

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.briefing import routes, service, voice, custom_voice
from app.accounts import User, VoiceProfile
from test_briefing_http import api, wait_for_edition
from test_listener_workflow import session


def auth(api):
    token = api.post("/api/v1/auth/demo", json={"profile": "tech"}).json()[
        "access_token"
    ]
    return {"Authorization": "Bearer " + token}


def recording(seconds):
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        target.writeframes(b"\x01\0" * (8000 * seconds))
    return {"file": ("recording.wav", out.getvalue(), "audio/wav")}


def test_premium_gate_applies_to_selection_preview_and_profile_id(api):
    headers = auth(api)
    row = next(
        v
        for v in api.get("/api/v1/voices", headers=headers).json()
        if v["id"] == "gangsta"
    )
    assert row["premium"] and row["locked"]
    assert (
        api.patch(
            "/api/v1/users/me/preferences",
            headers=headers,
            json={"voice_profile_id": "gangsta"},
        ).status_code
        == 403
    )
    assert (
        api.post("/api/v1/voices/gangsta/preview", headers=headers).status_code == 403
    )
    with routes.SessionLocal() as db:
        profile_id = db.scalar(
            select(VoiceProfile.id).where(VoiceProfile.slug == "gangsta")
        )
    assert (
        api.post(
            "/api/v1/briefings", headers=headers, json={"voice_profile_id": profile_id}
        ).status_code
        == 403
    )
    uid = api.get("/api/v1/users/me", headers=headers).json()["id"]
    with routes.SessionLocal() as db:
        db.get(User, uid).is_premium = True
        db.commit()
    assert (
        api.patch(
            "/api/v1/users/me/preferences",
            headers=headers,
            json={"voice_profile_id": "gangsta"},
        ).status_code
        == 200
    )


def test_both_editions_are_prepared_idempotently_and_voice_changes_reuse_scripts(
    api, monkeypatch
):
    monkeypatch.setenv("DAILY_NEWS_PERIOD", "week")
    headers = auth(api)
    pair = api.post("/api/v1/briefings/prepare", headers=headers).json()
    assert pair["daily"]["id"] != pair["weekly"]["id"]
    again = api.post("/api/v1/briefings/prepare", headers=headers).json()
    assert {k: v["id"] for k, v in pair.items()} == {
        k: v["id"] for k, v in again.items()
    }
    for item in pair.values():
        assert (
            wait_for_edition(api, "/api/v1/briefings/" + item["id"], headers)["status"]
            == "completed"
        )
    monkeypatch.setattr(
        service,
        "generate_script",
        lambda *args: pytest.fail("Voice-only preparation must reuse the script"),
    )
    api.patch(
        "/api/v1/users/me/preferences",
        headers=headers,
        json={"voice_profile_id": "jarvis"},
    )
    changed = api.post("/api/v1/briefings/prepare", headers=headers).json()
    for kind, item in changed.items():
        assert item["id"] != pair[kind]["id"]
        done = wait_for_edition(api, "/api/v1/briefings/" + item["id"], headers)
        assert done["status"] == "completed" and done["voice_profile_id"] == "jarvis"


def test_named_demo_character_creates_in_one_step_and_keeps_recording_on_failure(
    api, monkeypatch
):
    headers, other = auth(api), auth(api)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    calls = []

    def clone(key, sample, name):
        calls.append(name)
        with wave.open(io.BytesIO(sample)) as media:
            assert 89 <= media.getnframes() / media.getframerate() <= 91
        if len(calls) == 1:
            raise HTTPException(502, "Try again")
        return "private-created-voice"

    monkeypatch.setattr(custom_voice, "clone_voice", clone)
    path = "/api/v1/users/me/custom-voice"
    result = api.post(
        path,
        headers=headers,
        data={"name": "My narrator", "consent": "true"},
        files=recording(90),
    )
    assert result.status_code == 502
    saved = api.get(path, headers=headers).json()
    assert saved["name"] == "My narrator" and saved["sample_uploaded"]
    assert api.get(path, headers=other).json()["sample_uploaded"] is False
    result = api.post(path + "/create", headers=headers)
    assert (
        result.status_code == 200 and result.json()["saved"] and result.json()["active"]
    )
    assert result.json()["name"] == "My narrator" and result.json()["revision"]
    assert "private-created-voice" not in result.text
    assert calls == ["My narrator", "My narrator"]


def test_missing_paragraph_pauses_are_added_without_changing_verified_words(
    session, monkeypatch
):
    text = "A.\n\nB."
    monkeypatch.setenv("ELEVENLABS_API_KEY", "key")
    monkeypatch.setattr(voice, "convert_audio", lambda _: b"\x01\0" * (voice.RATE * 2))

    def speech(url, **kwargs):
        assert kwargs["json"]["text"] == text
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "audio_base64": base64.b64encode(b"encoded").decode(),
                "alignment": {
                    "characters": list(text),
                    "character_start_times_seconds": [0, 0.2, 0.21, 0.22, 0.3, 0.45],
                    "character_end_times_seconds": [0.18, 0.2, 0.21, 0.22, 0.43, 0.45],
                },
            },
        )

    monkeypatch.setattr(voice.httpx, "post", speech)
    pcm, cues = voice.render_aligned(
        session,
        [("A.", "en"), ("B.", "en")],
        ("elevenlabs", "test", "voice"),
        "pause-test",
        pauses=[0.7],
    )
    assert cues[1][0] == pytest.approx(0.88, abs=0.001)
    assert len(pcm) / (2 * voice.RATE) == pytest.approx(2.78, abs=0.001)
    assert cues[0][1] == cues[1][0]
    assert cues[-1][1] == pytest.approx(len(pcm) / (2 * voice.RATE))
