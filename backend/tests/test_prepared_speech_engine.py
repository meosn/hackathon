from app.accounts import set_preferences
from app.briefing import service, voice
from app.briefing.contracts import BriefingRequest
from app.briefing.daily import daily_key
from test_listener_workflow import session, listener


def test_selected_engine_is_frozen_and_used_for_prepared_audio(session, monkeypatch):
    user=listener(session,'speech-engine','en',['technology'])
    set_preferences(session,user.id,{'voice_engine':'openai'})
    item=service.create_briefing(session,user.id,BriefingRequest(period='week'))
    service.generate_script(session,item.id)
    assert item.request['voice_engine']=='openai'
    expected=item.request['openai_voice']
    set_preferences(session,user.id,{'voice_engine':'elevenlabs'})
    monkeypatch.setenv('TTS_PROVIDER','elevenlabs')
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    seen=[]
    original=voice.render_audio
    def render(db,rows,profile,reference,config=None):
        seen.append(config)
        return original(db,rows,profile,reference,config=('local','espeak-ng',profile))
    monkeypatch.setattr(voice,'render_audio',render)
    assert service.synthesize_briefing(session,item.id)=='completed'
    assert seen==[('openai','gpt-4o-mini-tts',expected)]


def test_provider_changes_daily_audio_identity(monkeypatch):
    from datetime import date
    monkeypatch.setenv('TTS_PROVIDER','elevenlabs')
    prefs=dict(language='en',duration_minutes=5,depth='standard',interests=[],preferred_sources=[],excluded_sources=[],voice_profile_id='professional',voice_engine='openai')
    first=daily_key('listener',prefs,date(2026,11,21))
    second=daily_key('listener',{**prefs,'voice_engine':'elevenlabs'},date(2026,11,21))
    assert first != second
