import base64
import json
import pytest
import httpx
from sqlalchemy import select
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from app import notifications as n, voice_library as v
from app.accounts import set_preferences
from app.briefing.models import Briefing, Conversation
from app.briefing.providers import model_output
from app.briefing.contracts import Decision
from test_listener_workflow import session, listener
from test_briefing_http import api

def test_favorites_and_custom_collection_are_private_persist_and_delete(session):
    owner=listener(session,'collection','en',[])
    other=listener(session,'other-collection','en',[])
    assert {x['id'] for x in v.collection(session,owner) if x['favorite']}=={'professional','energetic'}
    owner.custom_voice_id,owner.custom_voice_name='one','First voice'
    first=v.remember(session,owner)
    owner.custom_voice_id,owner.custom_voice_name='two','Second voice'
    owner.custom_voice_active=True
    second=v.remember(session,owner)
    key='custom:'+first.id
    assert len([x for x in v.collection(session,owner) if x['custom']])==2
    assert not [x for x in v.collection(session,other) if x['custom']]
    with pytest.raises(Exception) as error:v.choose_voice(key,session,other)
    assert error.value.status_code==404
    v.choose_voice(key,session,owner)
    assert owner.custom_voice_id=='one' and owner.custom_voice_active
    v.change_voice(key,v.LibraryPatch(favorite=False),session,owner)
    assert not next(x for x in v.collection(session,owner) if x['id']==key)['favorite']
    v.remove_voice(key,session,owner)
    assert owner.custom_voice_id is None and not owner.custom_voice_active
    assert session.get(v.ListenerVoice,second.id) is not None
    v.remove_voice('jarvis',session,owner)
    assert next(x for x in v.collection(session,owner) if x['id']=='jarvis')['hidden']
    assert not next(x for x in v.collection(session,other) if x['id']=='jarvis')['hidden']
    v.change_voice('jarvis',v.LibraryPatch(hidden=False),session,owner)
    assert not next(x for x in v.collection(session,owner) if x['id']=='jarvis')['hidden']

def subscription():
    public=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    encode=lambda x:base64.urlsafe_b64encode(x).decode().rstrip('=')
    return {'endpoint':'https://fcm.googleapis.com/fcm/send/test-endpoint','keys':{'p256dh':encode(public),'auth':encode(b'0'*16)}}

def test_notifications_are_owner_scoped_and_push_subscription_can_be_disabled(api):
    def auth():return {'Authorization':'Bearer '+api.post('/api/v1/auth/demo',json={'profile':'tech'}).json()['access_token']}
    first,other=auth(),auth()
    data=subscription()
    assert api.post('/api/v1/notifications/subscriptions',headers=first,json=data).status_code==201
    assert api.post('/api/v1/notifications/subscriptions',headers=first,json={**data,'endpoint':'https://127.0.0.1/private'}).status_code==422
    api.request('DELETE','/api/v1/notifications/subscriptions',headers=other,json={'endpoint':data['endpoint']})
    assert api.post('/api/v1/notifications/subscriptions/status',headers=first,json={'endpoint':data['endpoint']}).json()['enabled']
    assert api.post('/api/v1/notifications/test',headers=first).status_code==202
    rows=api.get('/api/v1/notifications',headers=first).json()
    assert len(rows)==1 and rows[0]['url']=='/'
    assert api.get('/api/v1/notifications',headers=other).json()==[]
    assert api.post('/api/v1/notifications/'+rows[0]['id']+'/read',headers=other).status_code==404
    assert api.post('/api/v1/notifications/'+rows[0]['id']+'/read',headers=first).status_code==204
    assert api.get('/api/v1/notifications',headers=first).json()[0]['read']
    assert api.request('DELETE','/api/v1/notifications/subscriptions',headers=first,json={'endpoint':data['endpoint']}).status_code==204
    assert not api.post('/api/v1/notifications/subscriptions/status',headers=first,json={'endpoint':data['endpoint']}).json()['enabled']

def test_ready_notification_waits_for_audio_stage_and_delivery_is_idempotent(session,monkeypatch,tmp_path):
    import pywebpush
    from app.config import settings
    from app.jobs import ProcessingJob
    owner=listener(session,'ready-push','en',[])
    data=subscription()
    sub=n.PushSubscription(user_id=owner.id,**data)
    session.add(sub);session.commit()
    edition=Briefing(user_id=owner.id,title='News',language='en',voice_profile_id='professional',request={},schedule_key='scheduled/test',status='audio_generating')
    session.add(edition);session.flush()
    assert n.record_ready(session,edition) is None
    edition.status='failed';assert n.record_ready(session,edition) is None
    edition.status='completed'
    notice=n.record_ready(session,edition);session.commit()
    assert n.record_ready(session,edition).id==notice.id
    assert len(session.scalars(select(ProcessingJob).where(ProcessingJob.kind=='notification')).all())==1
    monkeypatch.setattr(settings,'state_dir',tmp_path)
    calls=[]
    monkeypatch.setattr(pywebpush,'webpush',lambda **kw:calls.append(kw))
    n.deliver(session,notice.id);n.deliver(session,notice.id)
    assert len(calls)==1
    assert json.loads(calls[0]['data'])['url']=='/briefings/'+edition.id
    assert calls[0]['subscription_info']['keys']==data['keys']
    assert n.vapid_keys()[1]==n.vapid_keys()[1]
    assert (tmp_path/'web-push-private.pem').stat().st_mode & 0o077==0

def test_local_model_uses_private_ollama_without_api_credentials_or_cloud_fallback(session,monkeypatch):
    owner=listener(session,'local-questions','en',[])
    set_preferences(session,owner.id,{'discussion_model':'local'})
    conv=Conversation(user_id=owner.id,language='en')
    session.add(conv);session.commit()
    monkeypatch.setenv('LLM_PROVIDER','api')
    monkeypatch.setenv('LLM_API_KEY','must-not-reach-local-host')
    monkeypatch.setenv('LOCAL_LLM_ENABLED','1')
    monkeypatch.setenv('LOCAL_LLM_BASE_URL','http://private-ollama:11434')
    monkeypatch.setenv('LOCAL_LLM_MODEL','qwen3:0.6b')
    seen=[]
    def response(request):
        seen.append(request)
        return httpx.Response(200,json={'message':{'content':'{"intent":"FOLLOW_UP"}'},'prompt_eval_count':30,'eval_count':10})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(response),**kw))
    result=model_output(session,conv.id,[{'role':'user','content':'Explain'}],Decision)
    assert result.intent=='FOLLOW_UP'
    body=json.loads(seen[0].content)
    assert str(seen[0].url)=='http://private-ollama:11434/api/chat'
    assert 'Authorization' not in seen[0].headers
    assert body['model']=='qwen3:0.6b' and body['think'] is False
    monkeypatch.setenv('LOCAL_LLM_ENABLED','0')
    with pytest.raises(ValueError,match='unavailable'):model_output(session,conv.id,[],Decision)
    assert len(seen)==1

def test_scheduled_edition_uses_the_selected_private_voice(session):
    from datetime import datetime, UTC
    from app.accounts import Schedule
    from app.jobs import discover
    owner=listener(session,'scheduled-custom','en',[])
    owner.custom_voice_id,owner.custom_voice_active='private-narrator',True
    session.add(Schedule(user_id=owner.id,time='00:00',timezone='UTC',enabled=True))
    session.commit()
    discover(session,datetime.now(UTC))
    edition=session.scalar(select(Briefing).where(Briefing.user_id==owner.id))
    assert edition.voice_profile_id=='custom'
    assert edition.request['narrator_voice_id']=='private-narrator'
