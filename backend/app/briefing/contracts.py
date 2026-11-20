from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BriefingRequest(Strict):
    period: Literal["day", "week", "month"] = "day"
    topic: str | None = Field(default=None, min_length=1, max_length=100)
    duration_minutes: int | None = Field(default=None, ge=1, le=30)
    language: Literal["en", "de", "nl"] | None = None
    voice_profile_id: str | None = Field(default=None, min_length=1, max_length=80)
    selected_story_ids: list[str] = Field(default_factory=list, max_length=100)
    story_limit: int | None = Field(default=None, ge=1, le=30)


class Line(Strict):
    story_id: str
    claim_id: str
    text: str = Field(min_length=1, max_length=1500)


class Script(Strict):
    lines: list[Line] = Field(min_length=1, max_length=60)


class Answer(Strict):
    lines: list[Line] = Field(default_factory=list, max_length=6)


class Entailment(Strict):
    supported: bool


class StartConversation(Strict):
    briefing_id: str | None = None
    story_id: str | None = None


class AgentContextRequest(Strict):
    briefing_id: str | None = Field(default=None, min_length=1, max_length=80)
    story_id: str | None = Field(default=None, min_length=1, max_length=80)
    playback_seconds: float = Field(default=0, ge=0, le=86400)
    more_news: bool = False


class AgentContext(BaseModel):
    context: str


class AgentSession(AgentContext):
    signed_url: str


class MessageInput(Strict):
    text: str = Field(min_length=1, max_length=2000)


Intent = Literal[
    "GET_LATEST_NEWS",
    "GET_PERIOD_NEWS",
    "GET_MORE_NEWS",
    "FILTER_TOPIC",
    "SELECT_STORY",
    "EXPLAIN_STORY",
    "COMPARE_SOURCES",
    "FOLLOW_UP",
    "CHANGE_VOICE",
    "CHANGE_PREFERENCES",
    "SKIP_STORY",
    "STOP_PLAYBACK",
    "RESUME_PLAYBACK",
]


class Decision(Strict):
    intent: Intent
    ordinal: int | None = Field(default=None, ge=1, le=100)
    topic: str | None = Field(default=None, max_length=100)
    period: Literal["day", "week", "month"] = "day"
    retrieval_query: str | None = Field(default=None, max_length=1000)


class Queued(BaseModel):
    briefing_id: str
    status: Literal["queued"]


class Citation(BaseModel):
    article_id: str
    claim_id: str
    title: str
    source: str
    source_id: str
    url: str
    excerpt: str
    start: int
    end: int
    is_synthetic: bool


class Segment(BaseModel):
    id: str
    story_id: str | None
    position: int
    language: str
    text: str
    claim_ids: list[str]
    source_article_ids: list[str]
    citations: list[Citation]
    verification_status: str
    start_seconds: float
    end_seconds: float


class Item(BaseModel):
    story_id: str
    position: int
    title: str


class BriefingView(BaseModel):
    id: str
    title: str
    created_at: datetime
    status: Literal[
        "queued",
        "processing",
        "script_ready",
        "audio_generating",
        "completed",
        "failed",
    ]
    language: str
    voice_profile_id: str
    error: str | None
    duration_seconds: float
    progress: int
    period: str


class BriefingDetail(BriefingView):
    audio_provider: str | None
    items: list[Item]
    segments: list[Segment]


class MessageView(BaseModel):
    id: str
    created_at: datetime
    story_id: str | None
    briefing_id: str | None
    role: Literal["assistant", "user"]
    text: str
    intent: Intent | None
    citations: list[Citation]
    action: dict


class TranscribedReply(MessageView):
    transcription: str


class ConversationView(BaseModel):
    id: str
    briefing_id: str | None
    story_id: str | None
    topic: str | None
    language: str
    messages: list[MessageView]


class RealtimeEvidence(MessageView):
    context: dict


class SpeechSession(BaseModel):
    token: str
    voice_id: str
    voice_profile_id: str
    model_id: str
    sample_rate: int
