import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.accounts import User, preferences, set_preferences
from app.auth import current_user, user_for_token
from app.config import settings
from app.db import SessionLocal, get_db
from app.messaging import emit
from app.news.service import story_detail
from . import agent, characters, conversation_speech, custom_voice, realtime, research, service, voice
from .accounting import account_attempts
from . import contracts
from .contracts import BriefingRequest, MessageInput, StartConversation
from .discussion import message_view, respond
from .models import (
    Briefing,
    BriefingItem,
    BriefingSegment,
    Conversation,
    ConversationMessage,
    GeneratedAudio,
    ListeningHistory,
    UserFeedback,
)
from .ranking import recommendations

router = APIRouter()


def owned(db, kind, item_id, user_id, lock=False):
    query = select(kind).where(kind.id == item_id, kind.user_id == user_id)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if not item:
        raise HTTPException(404, "Item not found")
    return item


def queue(db, item):
    from app.jobs import enqueue_briefing

    enqueue_briefing(item.id)
    return {"briefing_id": item.id, "status": "queued"}


@router.post(
    "/briefings/{briefing_id}/revoice", status_code=202, response_model=contracts.Queued
)
def revoice_briefing(briefing_id: str, db=Depends(get_db), user=Depends(current_user)):
    from app.jobs import enqueue

    source = owned(db, Briefing, briefing_id, user.id)
    try:
        item = service.revoice_briefing(db, source, user.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    enqueue("voice", item.id)
    return {"briefing_id": item.id, "status": "queued"}


@router.post("/briefings", status_code=202, response_model=contracts.Queued)
def request_briefing(
    data: BriefingRequest, db=Depends(get_db), user=Depends(current_user)
):
    try:
        item = service.create_briefing(db, user.id, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return queue(db, item)


@router.post(
    "/briefings/{briefing_id}/retry", status_code=202, response_model=contracts.Queued
)
def retry(briefing_id: str, db=Depends(get_db), user=Depends(current_user)):
    item = owned(db, Briefing, briefing_id, user.id)
    item = service.lock_briefing(db, item.id)
    if item.status != "failed":
        raise HTTPException(409, "Only failed briefings can be retried")
    db.execute(delete(BriefingSegment).where(BriefingSegment.briefing_id == item.id))
    db.execute(delete(BriefingItem).where(BriefingItem.briefing_id == item.id))
    item.status, item.error, item.audio_id, item.duration_seconds = (
        "queued",
        None,
        None,
        0,
    )
    from app.jobs import ProcessingJob

    db.execute(
        delete(ProcessingJob).where(
            ProcessingJob.entity_id == item.id,
            ProcessingJob.kind.in_(["briefing", "voice"]),
        )
    )
    emit(db, "briefing.requested", item.id)
    db.commit()
    return queue(db, item)


@router.get("/briefings", response_model=list[contracts.BriefingView])
def list_briefings(db=Depends(get_db), user=Depends(current_user)):
    items = db.scalars(
        select(Briefing)
        .where(Briefing.user_id == user.id)
        .order_by(Briefing.created_at.desc())
        .limit(150)
    )
    return [service.briefing_view(db, item) for item in items]


@router.post("/briefings/daily", response_model=contracts.BriefingDetail)
def prepared_daily(db=Depends(get_db), user=Depends(current_user)):
    from .daily import prepare_listener
    from app.jobs import recover

    item = prepare_listener(db, user.id)
    db.commit()
    recover()
    return service.briefing_view(db, item, detail=True)


@router.post("/briefings/daily", response_model=contracts.BriefingDetail)
def daily_briefing(db=Depends(get_db), user=Depends(current_user)):
    from .daily import prepare_listener
    from app.jobs import recover

    item = prepare_listener(db, user.id)
    db.commit()
    recover()
    return service.briefing_view(db, item, detail=True)


@router.get("/briefings/{briefing_id}", response_model=contracts.BriefingDetail)
def get_briefing(briefing_id: str, db=Depends(get_db), user=Depends(current_user)):
    return service.briefing_view(
        db, owned(db, Briefing, briefing_id, user.id), detail=True
    )


@router.get(
    "/briefings/{briefing_id}/transcript", response_model=list[contracts.Segment]
)
def transcript(briefing_id: str, db=Depends(get_db), user=Depends(current_user)):
    owned(db, Briefing, briefing_id, user.id)
    return [service.segment_view(row) for row in service.segments_for(db, briefing_id)]


@router.get("/briefings/{briefing_id}/sources", response_model=list[contracts.Citation])
def sources(briefing_id: str, db=Depends(get_db), user=Depends(current_user)):
    owned(db, Briefing, briefing_id, user.id)
    return [c for row in service.segments_for(db, briefing_id) for c in row.citations]


@router.post("/agent-session", response_model=contracts.AgentSession)
def agent_session(
    response: Response,
    data: contracts.AgentContextRequest = contracts.AgentContextRequest(),
    db=Depends(get_db),
    user=Depends(current_user),
):
    agent_id, api_key = agent.require_agent()
    context = agent.context_for(db, user.id, data)
    character = characters.selected(db, user)
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "signed_url": agent.signed_session_url(agent_id, api_key),
        "context": context,
        "voice_id": character["voice_id"],
        "persona": character["persona"],
        "language": character["language"],
    }


@router.get("/voice-engines", response_model=list[contracts.VoiceEngine])
def voice_engines(user=Depends(current_user)):
    return [
        {"id": "openai", "name": "OpenAI Realtime", "available": realtime.enabled(), "description": "Direct speech-to-speech with OpenAI voices."},
        {"id": "elevenlabs", "name": "ElevenLabs Realtime", "available": agent.available(), "description": "Live voice chat over WebSocket with character and custom voices."},
    ]


def custom_voice_key(user):
    if user.is_demo:
        return None
    return os.getenv("ELEVENLABS_API_KEY") or None


def custom_voice_view(db, user):
    uploaded = db.scalar(
        select(User.custom_voice_sample.is_not(None)).where(User.id == user.id)
    )
    return {
        "name": user.custom_voice_name,
        "persona": user.custom_voice_persona,
        "saved": bool(user.custom_voice_id),
        "active": bool(user.custom_voice_id and user.custom_voice_active),
        "can_upload": not user.custom_voice_id,
        "can_create": bool(custom_voice_key(user)),
        "sample_uploaded": bool(uploaded),
    }


@router.get("/users/me/custom-voice", response_model=contracts.CustomVoice)
def get_custom_voice(db=Depends(get_db), user=Depends(current_user)):
    return custom_voice_view(db, user)


def lock_custom_voice_owner(db, user):
    owner = db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if owner.custom_voice_id:
        raise HTTPException(409, "A custom voice is already saved for this listener.")
    return owner


def provision_custom_voice(owner, api_key, sample):
    owner.custom_voice_id = custom_voice.clone_voice(api_key, sample)
    owner.custom_voice_active = True
    owner.custom_voice_sample = None


@router.post(
    "/users/me/custom-voice", response_model=contracts.CustomVoice, status_code=201
)
def upload_custom_voice(
    file: UploadFile = File(...),
    consent: bool = Form(...),
    name: str = Form("Custom", min_length=1, max_length=80),
    persona: str = Form("Natural, conversational delivery.", min_length=1, max_length=600),
    db=Depends(get_db),
    user=Depends(current_user),
):
    if not consent:
        raise HTTPException(422, "Confirm permission to clone the recorded voice.")
    sample = custom_voice.checked_sample(file)
    owner = lock_custom_voice_owner(db, user)
    owner.custom_voice_name, owner.custom_voice_persona = name.strip() or "Custom", persona.strip() or "Natural, conversational delivery."
    api_key = custom_voice_key(owner)
    if api_key:
        provision_custom_voice(owner, api_key, sample)
        set_preferences(db, owner.id, {"voice_engine": "elevenlabs"})
    else:
        owner.custom_voice_sample = sample
    db.commit()
    return custom_voice_view(db, owner)


@router.post("/users/me/custom-voice/create", response_model=contracts.CustomVoice)
def create_custom_voice(db=Depends(get_db), user=Depends(current_user)):
    api_key = custom_voice_key(user)
    if not api_key:
        raise HTTPException(
            503, "A personal account and configured ElevenLabs key are required."
        )
    owner = lock_custom_voice_owner(db, user)
    if not owner.custom_voice_sample:
        raise HTTPException(404, "Upload a voice sample first.")
    provision_custom_voice(owner, api_key, owner.custom_voice_sample)
    set_preferences(db, owner.id, {"voice_engine": "elevenlabs"})
    db.commit()
    return custom_voice_view(db, owner)


@router.patch("/users/me/custom-voice", response_model=contracts.CustomVoice)
def select_custom_voice(
    data: contracts.SelectCustomVoice,
    db=Depends(get_db),
    user=Depends(current_user),
):
    if data.active:
        if not user.custom_voice_id:
            raise HTTPException(404, "No custom voice is saved for this listener.")
    if data.active is not None:
        user.custom_voice_active = data.active
    if data.name is not None:
        user.custom_voice_name = data.name.strip() or "Custom"
    if data.persona is not None:
        user.custom_voice_persona = data.persona.strip() or "Natural, conversational delivery."
    if data.active:
        set_preferences(db, user.id, {"voice_engine": "elevenlabs"})
    db.commit()
    return custom_voice_view(db, user)


@router.post("/agent-context", response_model=contracts.AgentContext)
def agent_context(
    response: Response,
    data: contracts.AgentContextRequest = contracts.AgentContextRequest(),
    db=Depends(get_db),
    user=Depends(current_user),
):
    agent.require_agent()
    response.headers["Cache-Control"] = "private, no-store"
    return {"context": agent.context_for(db, user.id, data)}


def audio_response(audio):
    try:
        data = voice.read_object(audio.object_key)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(503, "Audio storage is currently unavailable") from exc
    return Response(
        content=data,
        media_type="audio/wav",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/briefings/{briefing_id}/audio", response_class=Response)
def get_audio(briefing_id: str, db=Depends(get_db), user=Depends(current_user)):
    item = owned(db, Briefing, briefing_id, user.id)
    if item.status != "completed" or not item.audio_id:
        raise HTTPException(409, "Audio is not ready")
    return audio_response(db.get(GeneratedAudio, item.audio_id))


@router.get("/recommendations")
def recommended(
    period: Literal["day", "week", "month"] = "week",
    topic: str | None = None,
    db=Depends(get_db),
    user=Depends(current_user),
):
    return recommendations(db, user.id, period=period, topic=topic)


class FeedbackInput(BaseModel):
    score: Literal[-1, 0, 1]


def update_story_signal(db, model, user_id, story_id, score=None):
    if not story_detail(db, story_id):
        raise HTTPException(404, "Story not found")
    query = select(model).where(model.user_id == user_id, model.story_id == story_id)
    item = db.scalar(query)
    if not item:
        try:
            with db.begin_nested():
                item = model(user_id=user_id, story_id=story_id)
                if score is not None:
                    item.score = score
                db.add(item)
                db.flush()
        except IntegrityError:
            item = db.scalars(query).one()
    if score is not None:
        item.score = score
    db.commit()


@router.put("/listening-history/{story_id}", status_code=204)
def listened(story_id: str, db=Depends(get_db), user=Depends(current_user)):
    update_story_signal(db, ListeningHistory, user.id, story_id)
    return Response(status_code=204)


@router.put("/feedback/{story_id}", status_code=204)
def feedback(
    story_id: str, data: FeedbackInput, db=Depends(get_db), user=Depends(current_user)
):
    update_story_signal(db, UserFeedback, user.id, story_id, data.score)
    return Response(status_code=204)


@router.websocket("/ws/briefings/{briefing_id}")
async def status_socket(ws: WebSocket, briefing_id: str):
    origin = ws.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        payload = await asyncio.wait_for(ws.receive_json(), timeout=6)
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str):
            await ws.close(code=1008)
            return
        previous = None
        while True:
            with SessionLocal() as db:
                user = user_for_token(db, token)
                item = (
                    db.scalar(
                        select(Briefing).where(
                            Briefing.id == briefing_id, Briefing.user_id == user.id
                        )
                    )
                    if user
                    else None
                )
                if not item:
                    await ws.close(code=1008)
                    return
                status = item.status
            if previous != status:
                await ws.send_json(
                    {
                        "event": f"briefing.{status}",
                        "status": status,
                        "progress": service.PROGRESS[status],
                        "timestamp": datetime.now(UTC).isoformat(),
                        "briefing_id": briefing_id,
                    }
                )
                previous = status
            if status in {"completed", "failed"}:
                await ws.close(code=1000)
                return
            await asyncio.sleep(0.6)
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError):
        return


@router.post(
    "/conversations", status_code=201, response_model=contracts.ConversationView
)
def start_conversation(
    data: StartConversation = StartConversation(),
    db=Depends(get_db),
    user=Depends(current_user),
):
    if data.briefing_id:
        owned(db, Briefing, data.briefing_id, user.id)
    if data.story_id and not story_detail(db, data.story_id):
        raise HTTPException(404, "Story not found")
    conv = Conversation(
        user_id=user.id,
        briefing_id=data.briefing_id,
        story_id=data.story_id,
        language=preferences(db, user.id)["language"],
    )
    db.add(conv)
    db.commit()
    return conversation_view(db, conv)


def conversation_view(db, conv):
    messages = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conv.id)
        .order_by(ConversationMessage.created_at, ConversationMessage.id)
    )
    return {
        key: getattr(conv, key)
        for key in ("id", "briefing_id", "story_id", "topic", "language")
    } | {"messages": [message_view(m) for m in messages]}


@router.get(
    "/conversations/{conversation_id}", response_model=contracts.ConversationView
)
def get_conversation(
    conversation_id: str, db=Depends(get_db), user=Depends(current_user)
):
    return conversation_view(db, owned(db, Conversation, conversation_id, user.id))


@router.post(
    "/conversations/{conversation_id}/messages", response_model=contracts.MessageView
)
def send_message(
    conversation_id: str,
    data: MessageInput,
    db=Depends(get_db),
    user=Depends(current_user),
):
    conv = owned(db, Conversation, conversation_id, user.id, lock=True)
    try:
        with account_attempts(db):
            return message_view(respond(db, conv, data.text))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post(
    "/conversations/{conversation_id}/audio", response_model=contracts.TranscribedReply
)
def send_recording(
    conversation_id: str,
    file: UploadFile = File(...),
    story_id: str | None = Form(None),
    db=Depends(get_db),
    user=Depends(current_user),
):
    conv = owned(db, Conversation, conversation_id, user.id, lock=True)
    if agent.conversation_provider() == "elevenagents":
        raise HTTPException(409, "Voice conversations use ElevenAgents")
    if story_id and conv.briefing_id:
        membership = db.scalar(
            select(BriefingItem.id).where(
                BriefingItem.briefing_id == conv.briefing_id,
                BriefingItem.story_id == story_id,
            )
        )
        if not membership:
            raise HTTPException(422, "Story is outside this briefing")
        conv.story_id = story_id
    content = file.file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Recording exceeds 10 MiB")
    emit(db, "voice.transcription.requested", conv.id)
    try:
        with account_attempts(db):
            text = voice.transcribe(
                db, content, file.content_type or "", conv.language, conv.id
            )
            emit(db, "voice.transcription.completed", conv.id)
            return message_view(respond(db, conv, text)) | {"transcription": text}
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            503, "Transcription provider is currently unavailable"
        ) from exc


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}/audio",
    response_class=Response,
)
def spoken_answer(
    conversation_id: str,
    message_id: str,
    db=Depends(get_db),
    user=Depends(current_user),
):
    conv = owned(db, Conversation, conversation_id, user.id)
    msg = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.id == message_id,
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.role == "assistant",
        )
    )
    if not msg:
        raise HTTPException(404, "Answer not found")
    prefs = preferences(db, user.id)
    with account_attempts(db):
        audio = voice.render_audio(
            db,
            [SimpleNamespace(text=msg.text, language=conv.language)],
            prefs["voice_profile_id"],
            msg.id,
        )
        db.commit()
    return audio_response(audio)


@router.post("/conversations/{conversation_id}/realtime", response_class=Response)
def realtime_session(
    conversation_id: str,
    data: "realtime.Offer",
    db=Depends(get_db),
    user=Depends(current_user),
):
    conv = owned(db, Conversation, conversation_id, user.id)
    titles = (
        list(
            db.scalars(
                select(BriefingItem.title)
                .where(BriefingItem.briefing_id == conv.briefing_id)
                .order_by(BriefingItem.position)
            )
        )
        if conv.briefing_id
        else []
    )
    context = realtime.evidence_context(db, conv)
    character = characters.selected(db, user)
    speech_stream = data.speech_stream and conversation_speech.enabled()
    sdp = realtime.negotiate(
        data.sdp, conv.language, titles, user.id, context, speech_stream,
        character["openai_voice"], character["persona"],
    )
    return Response(
        sdp,
        media_type="application/sdp",
        headers={
            "Cache-Control": "no-store",
            "X-Speech-Output": ("elevenlabs" if speech_stream else "openai"),
        },
    )


@router.post("/conversations/{conversation_id}/research", response_model=contracts.ResearchResult)
def research_topic(
    conversation_id: str,
    data: contracts.ResearchRequest,
    db=Depends(get_db),
    user=Depends(current_user),
):
    conv = owned(db, Conversation, conversation_id, user.id, lock=True)
    with account_attempts(db):
        return research.handle(db, conv, data)


@router.post(
    "/conversations/{conversation_id}/realtime-evidence",
    response_model=contracts.RealtimeEvidence,
)
def realtime_evidence(
    conversation_id: str,
    data: "realtime.Turn",
    db=Depends(get_db),
    user=Depends(current_user),
):
    conv = owned(db, Conversation, conversation_id, user.id, lock=True)
    if data.story_id:
        membership = db.scalar(
            select(BriefingItem.id).where(
                BriefingItem.briefing_id == conv.briefing_id,
                BriefingItem.story_id == data.story_id,
            )
        )
        previous = (
            db.scalars(
                select(ConversationMessage.action).where(
                    ConversationMessage.conversation_id == conv.id,
                    ConversationMessage.role == "assistant",
                )
            )
            if not membership and data.story_id != conv.story_id
            else []
        )
        if (
            not membership
            and data.story_id != conv.story_id
            and not any(
                data.story_id in action.get("story_ids", []) for action in previous
            )
        ):
            raise HTTPException(422, "Story is outside this conversation")
        conv.story_id = data.story_id
    with account_attempts(db):
        message = respond(
            db, conv, data.question, decision=data.decision, extractive=True
        )
        story_ids = message.action.get("story_ids") or (
            [message.story_id] if message.story_id else []
        )
        return message_view(message) | {
            "context": realtime.evidence_context(db, conv, story_ids)
        }


@router.post(
    "/conversations/{conversation_id}/speech-session",
    response_model=contracts.SpeechSession,
)
def speech_session(
    conversation_id: str,
    response: Response,
    db=Depends(get_db),
    user=Depends(current_user),
):
    owned(db, Conversation, conversation_id, user.id)
    if agent.conversation_provider() != "local":
        raise HTTPException(409, "Use the configured conversation provider")
    result = conversation_speech.session(preferences(db, user.id)["voice_profile_id"])
    response.headers["Cache-Control"] = "private, no-store"
    return result
