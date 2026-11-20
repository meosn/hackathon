from datetime import datetime
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .accounts import (
    Input,
    PreferencePatch,
    Schedule,
    User,
    VoiceProfile,
    demo_listener,
    preferences,
    set_preferences,
    timezone_name,
)
from .auth import current_user, dummy_hash, hash_password, password_matches, token
from .config import settings
from .db import get_db, utcnow
from .timezones import GMT_OFFSETS, gmt_name, resolve_timezone
from .usage import costs

from . import account_contracts as views

router = APIRouter()


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class Register(Login):
    name: str = Field(min_length=1, max_length=90)
    password: str = Field(min_length=8, max_length=256)


class Name(Input):
    name: str = Field(min_length=1, max_length=90)


class Demo(Input):
    profile: Literal["tech", "finance"]


def tokens(user):
    return {"access_token": token(user), "token_type": "bearer"}


@router.post("/auth/register", response_model=views.SessionToken, status_code=201)
def register(body: Register, db=Depends(get_db)):
    user = User(
        name=body.name,
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.flush()
        preferences(db, user.id)
        from .briefing.daily import prepare_listener

        prepare_listener(db, user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered")
    return tokens(user)


@router.post("/auth/login", response_model=views.SessionToken)
def login(body: Login, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    valid = password_matches(
        body.password, user.password_hash if user else dummy_hash()
    )
    if not user or not valid:
        raise HTTPException(401, "Invalid credentials")
    from .briefing.daily import prepare_listener

    prepare_listener(db, user.id)
    db.commit()
    return tokens(user)


@router.post("/auth/demo", response_model=views.SessionToken)
def demo(body: Demo, db=Depends(get_db)):
    if not settings.demo_mode:
        raise HTTPException(404, "Demo mode is disabled")
    user = demo_listener(db, body.profile)
    db.commit()
    return tokens(user)


def public(user):
    return {k: getattr(user, k) for k in ("id", "email", "name", "is_admin", "is_demo")}


@router.get("/auth/me", response_model=views.Listener)
@router.get("/users/me", response_model=views.Listener)
def me(user=Depends(current_user)):
    return public(user)


@router.patch("/users/me", response_model=views.Listener)
def edit_user(body: Name, user=Depends(current_user), db=Depends(get_db)):
    user.name = body.name
    db.commit()
    return public(user)


@router.get("/users/me/preferences", response_model=views.PreferenceView)
def get_preferences(user=Depends(current_user), db=Depends(get_db)):
    return preferences(db, user.id)


@router.patch("/users/me/preferences", response_model=views.PreferenceView)
def change_preferences(
    body: PreferencePatch, user=Depends(current_user), db=Depends(get_db)
):
    result = set_preferences(db, user.id, body.model_dump(exclude_none=True))
    db.commit()
    return result


class Interests(Input):
    interests: list[str] = Field(max_length=50)


class Sources(Input):
    preferred_sources: list[str] = Field(max_length=150)
    excluded_sources: list[str] = Field(max_length=150)


@router.get("/users/me/interests", response_model=views.TopicSelection)
def get_interests(user=Depends(current_user), db=Depends(get_db)):
    return {"interests": preferences(db, user.id)["interests"]}


@router.put("/users/me/interests", response_model=views.PreferenceView)
def put_interests(body: Interests, user=Depends(current_user), db=Depends(get_db)):
    return change_preferences(PreferencePatch(**body.model_dump()), user, db)


@router.put("/users/me/sources", response_model=views.PreferenceView)
def put_sources(body: Sources, user=Depends(current_user), db=Depends(get_db)):
    return change_preferences(PreferencePatch(**body.model_dump()), user, db)


@router.get("/voices", response_model=list[views.VoiceView])
def voices(user=Depends(current_user), db=Depends(get_db)):
    return [
        {"id": v.slug, "name": v.name, "description": v.description}
        for v in db.scalars(select(VoiceProfile).order_by(VoiceProfile.name))
    ]


Weekdays = list[Annotated[int, Field(strict=True, ge=0, le=6)]]


class SchedulePatch(Input):
    time: str | None = Field(None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str | None = Field(None, max_length=80)
    enabled: bool | None = None
    days_of_week: Weekdays | None = Field(None, min_length=1, max_length=7)

    @field_validator("days_of_week")
    @classmethod
    def distinct_days(cls, value):
        return sorted(set(value)) if value is not None else value

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        return timezone_name(value) if value is not None else value


class ScheduleInput(SchedulePatch):
    time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(max_length=80)
    enabled: bool = True
    days_of_week: Weekdays = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)


def schedule_data(s):
    return {k: getattr(s, k) for k in ("id", "time", "timezone", "enabled", "days_of_week")}


@router.get("/timezones", response_model=list[str])
def timezones(user=Depends(current_user)):
    return [gmt_name(offset) for offset in GMT_OFFSETS]


def validate_schedule_slots(rows):
    seen = set()
    for row in rows:
        for day in row["days_of_week"]:
            key = (row["timezone"], day, row["time"])
            if key in seen:
                raise HTTPException(422, "Choose distinct delivery times for each day")
            seen.add(key)


@router.put("/schedules", response_model=list[views.ScheduleView])
def replace_schedules(
    body: Annotated[list[ScheduleInput], Field(max_length=84)],
    user=Depends(current_user), db=Depends(get_db),
):
    """Save a listener's entire weekly plan atomically, preserving completed runs."""
    rows = [item.model_dump() for item in body]
    validate_schedule_slots(rows)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    previous = db.scalars(select(Schedule).where(Schedule.user_id == user.id).with_for_update()).all()
    identity = lambda row: (row.time, row.timezone, tuple(row.days_of_week))
    available = {identity(row): row for row in previous}
    selected = []
    now = utcnow()
    for data in rows:
        row = available.pop((data["time"], data["timezone"], tuple(data["days_of_week"])), None)
        newly_enabled = row is None or (not row.enabled and data["enabled"])
        if row is None:
            row = Schedule(user_id=user.id, **data)
            db.add(row)
        else:
            row.enabled = data["enabled"]
        if newly_enabled:
            local = now.astimezone(resolve_timezone(data["timezone"]))
            if data["time"] <= local.strftime("%H:%M"):
                row.last_local_date = local.date()
        selected.append(row)
    for row in previous:
        if row not in selected:
            db.delete(row)
    db.commit()
    return [schedule_data(row) for row in selected]


def owned_schedule(db, user, id):
    row = db.scalar(
        select(Schedule).where(Schedule.id == id, Schedule.user_id == user.id)
    )
    if not row:
        raise HTTPException(404, "Schedule not found")
    return row


@router.get("/schedules", response_model=list[views.ScheduleView])
def schedules(user=Depends(current_user), db=Depends(get_db)):
    return [
        schedule_data(s)
        for s in db.scalars(
            select(Schedule)
            .where(Schedule.user_id == user.id)
            .order_by(Schedule.created_at)
        )
    ]


@router.post("/schedules", response_model=views.ScheduleView, status_code=201)
def add_schedule(body: ScheduleInput, user=Depends(current_user), db=Depends(get_db)):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.scalars(select(Schedule).where(Schedule.user_id == user.id)).all()
    validate_schedule_slots([*(schedule_data(row) for row in existing), body.model_dump()])
    row = Schedule(user_id=user.id, **body.model_dump())
    db.add(row)
    db.commit()
    return schedule_data(row)


@router.patch("/schedules/{schedule_id}", response_model=views.ScheduleView)
def edit_schedule(
    schedule_id: str,
    body: SchedulePatch,
    user=Depends(current_user),
    db=Depends(get_db),
):
    row = owned_schedule(db, user, schedule_id)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    changes = body.model_dump(exclude_none=True)
    existing = db.scalars(select(Schedule).where(Schedule.user_id == user.id, Schedule.id != row.id)).all()
    validate_schedule_slots([*(schedule_data(other) for other in existing), {**schedule_data(row), **changes}])
    for k, v in changes.items():
        setattr(row, k, v)
    db.commit()
    return schedule_data(row)


@router.delete("/schedules/{schedule_id}", status_code=204)
def remove_schedule(schedule_id: str, user=Depends(current_user), db=Depends(get_db)):
    db.delete(owned_schedule(db, user, schedule_id))
    db.commit()
    return Response(status_code=204)


@router.get("/metrics/costs", response_model=views.CostReport)
def metrics(user=Depends(current_user), db=Depends(get_db)):
    if not (user.is_admin or (user.is_demo and settings.demo_mode)):
        raise HTTPException(403, "Operator or demo access required")
    return costs(db)


@router.get("/assistant/models", response_model=list[views.DiscussionModel])
def discussion_models(user=Depends(current_user)):
    import os

    provider = os.getenv("LLM_PROVIDER", "mock")
    name = os.getenv("LLM_MODEL") or {
        "ollama": "Local Ollama",
        "api": "API model",
        "mock": "Source search (offline)",
    }.get(provider, "Configured assistant")
    return [
        {
            "id": "grounded",
            "name": "Source search",
            "description": "Direct evidence and rule-based commands.",
            "available": True,
        },
        {
            "id": "configured",
            "name": name,
            "description": "Evidence retrieval with "
            + (
                "local intent rules."
                if provider == "mock"
                else provider + " conversation and evidence-grounded answers."
            ),
            "available": True,
        },
    ]
