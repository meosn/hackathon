from pathlib import Path
import runpy

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.accounts import VoiceProfile, set_preferences
from app.briefing import characters, daily, granny, preview, service, voice
from app.briefing.contracts import BriefingRequest
from app.voice_library import collection
from test_listener_workflow import session, listener


def test_granny_can_be_selected_and_previews_its_actual_voice(session, monkeypatch):
    user = listener(session, "granny", "en", [])
    entry = next(v for v in collection(session, user) if v["id"] == "granny")
    assert entry["name"] == "Granny Mode" and entry["favorite"] and not entry["locked"]
    set_preferences(session, user.id, {"voice_profile_id": "granny", "voice_engine": "elevenlabs"})
    character = characters.selected(session, user)
    assert character["voice_id"] == granny.VOICE_ID
    assert "politicians" in character["persona"] and "grandmother" in character["persona"]
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    captured = {}

    def render(db, rows, slug, reference, config, **kwargs):
        captured.update(text=" ".join(r.text for r in rows), config=config)
        return "audio"

    monkeypatch.setattr(voice, "_render_audio", render)
    assert preview.render(session, user, "granny", preview.PreviewRequest()) == "audio"
    assert captured["config"][2] == granny.VOICE_ID
    assert captured["text"] == granny.PREVIEWS["en"]


def test_granny_framing_preserves_claims_and_changes_back_on_revoice(session):
    user = listener(session, "granny-episode", "en", ["technology"])
    set_preferences(session, user.id, {"voice_profile_id": "granny"})
    item = service.create_briefing(session, user.id, BriefingRequest(period="week"))
    service.generate_script(session, item.id)
    rows = service.segments_for(session, item.id)
    assert rows[0].text == granny.FRAMING["en"][0]
    assert rows[-1].text == granny.FRAMING["en"][2]
    assert service.verified_script(session, rows)
    facts = [r.text for r in rows if r.claim_ids]
    service.synthesize_briefing(session, item.id)
    set_preferences(session, user.id, {"voice_profile_id": "professional"})
    normal = service.revoice_briefing(session, item, user.id)
    normal_rows = service.segments_for(session, normal.id)
    assert normal_rows[0].text == service.WORDS["en"][0]
    assert [r.text for r in normal_rows if r.claim_ids] == facts
    assert service.verified_script(session, normal_rows)
    service.synthesize_briefing(session, normal.id)
    set_preferences(session, user.id, {"voice_profile_id": "granny"})
    again = service.revoice_briefing(session, normal, user.id)
    again_rows = service.segments_for(session, again.id)
    assert again_rows[0].text == granny.FRAMING["en"][0]
    assert service.verified_script(session, again_rows)
    again_rows[0].text = "A fabricated political allegation."
    assert not service.verified_script(session, again_rows)


def test_prepared_episode_reframes_reused_script_for_granny(session, monkeypatch):
    monkeypatch.setenv("DAILY_NEWS_PERIOD", "week")
    monkeypatch.setenv("VOICE_DETAIL_FIT", "0")
    user = listener(session, "prepared-granny", "en", ["technology"])
    normal = daily.ensure_daily(session, user.id)
    session.commit()
    service.generate_script(session, normal.id)
    service.synthesize_briefing(session, normal.id)
    set_preferences(session, user.id, {"voice_profile_id": "granny"})
    item = daily.ensure_daily(session, user.id)
    session.flush()
    assert item.request["source_briefing_id"] == normal.id
    rows = service.segments_for(session, item.id)
    assert rows[0].text == granny.FRAMING["en"][0]
    assert service.verified_script(session, rows)


def test_granny_migration_adds_existing_database_preset_without_duplicates(session):
    session.query(VoiceProfile).filter_by(slug="granny").delete()
    session.flush()
    migration = Path(__file__).parents[1] / "alembic/versions/0014_granny_mode.py"
    with Operations.context(MigrationContext.configure(session.connection())):
        upgrade = runpy.run_path(str(migration))["upgrade"]
        upgrade()
        upgrade()
    session.expire_all()
    profile = session.scalar(select(VoiceProfile).where(VoiceProfile.slug == "granny"))
    assert profile.name == "Granny Mode"
    assert profile.elevenlabs_voice_id == granny.VOICE_ID and profile.persona == granny.PERSONA
