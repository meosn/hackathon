"""Public account responses. Credential hashes and storage keys never enter the wire schema."""

from pydantic import BaseModel


class SessionToken(BaseModel):
    access_token: str
    token_type: str


class Listener(BaseModel):
    is_premium: bool = False
    id: str
    email: str
    name: str
    is_admin: bool
    is_demo: bool


class PreferenceView(BaseModel):
    language: str
    duration_minutes: int
    voice_profile_id: str
    timezone: str
    depth: str
    discussion_model: str
    voice_engine: str
    interests: list[str]
    preferred_sources: list[str]
    excluded_sources: list[str]


class TopicSelection(BaseModel):
    interests: list[str]


class VoiceView(BaseModel):
    premium: bool = False
    locked: bool = False
    id: str
    name: str
    description: str


class ScheduleView(BaseModel):
    id: str
    time: str
    timezone: str
    enabled: bool
    days_of_week: list[int]


class CostReport(BaseModel):
    articles: int
    processed_records: int
    duplicates: int
    near_duplicates: int
    stories: int
    verified_claims: int
    conflicting_claims: int
    llm_calls: int
    embedding_calls: int
    stt_calls: int
    tts_characters: int
    input_tokens: int
    output_tokens: int
    measured_usd: float
    estimated_usd: float
    dataset_usd: float
    listener_usd: float
    compute_estimate_usd: float
    compute_usd_per_hour: float
    projected_10x_usd: float
    cost_per_story: float
    cost_per_briefing: float
    completed_briefings: int
    unpriced_events: int
    stage_seconds: dict[str, float]
    pricing_note: str


class DiscussionModel(BaseModel):
    id: str
    name: str
    description: str
    available: bool
