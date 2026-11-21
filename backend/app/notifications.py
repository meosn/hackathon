"""An owner-scoped inbox and browser Web Push for completed scheduled editions."""
import base64
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, ForeignKey, JSON, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.exc import IntegrityError
from .auth import current_user
from .db import Record, get_db
from .config import settings, enabled

class PushSubscription(Record):
    __tablename__ = "push_subscriptions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    keys: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ListenerNotification(Record):
    __tablename__ = "listener_notifications"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    briefing_id: Mapped[str | None] = mapped_column(ForeignKey("briefings.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_to: Mapped[list] = mapped_column(JSON, default=list)


def vapid_keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    root = settings.state_dir
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "web-push-private.pem"
    if not path.exists():
        private = ec.generate_private_key(ec.SECP256R1())
        content = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as tmp:
            tmp.write(content)
        try:
            os.link(tmp.name, path)
        except FileExistsError:
            pass
        finally:
            os.unlink(tmp.name)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return str(path), base64.urlsafe_b64encode(public).decode().rstrip("=")


def record_ready(db, briefing):
    if briefing.status != "completed" or not (briefing.schedule_key or "").startswith("scheduled/"):
        return None
    existing = db.scalar(select(ListenerNotification).where(ListenerNotification.briefing_id == briefing.id))
    if existing:
        return existing
    row = ListenerNotification(user_id=briefing.user_id, briefing_id=briefing.id, title="Your news is ready")
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return db.scalar(select(ListenerNotification).where(ListenerNotification.briefing_id == briefing.id))
    from .jobs import queue_record
    queue_record(db, "notification", row.id)
    return row


def deliver(db, notification_id):
    from pywebpush import webpush, WebPushException
    row = db.get(ListenerNotification, notification_id)
    if not row or not enabled("WEB_PUSH_ENABLED", True):
        return
    private, _ = vapid_keys()
    subscriptions = db.scalars(select(PushSubscription).where(PushSubscription.user_id == row.user_id, PushSubscription.active.is_(True), PushSubscription.created_at <= row.created_at)).all()
    for sub in subscriptions:
        if sub.id in row.sent_to:
            continue
        try:
            webpush(subscription_info={"endpoint": sub.endpoint, "keys": sub.keys}, data=json.dumps({"title": row.title, "body": "Your scheduled briefing is ready. Tap to listen.", "url": "/briefings/" + row.briefing_id if row.briefing_id else "/", "tag": row.id}),
                vapid_private_key=private, vapid_claims={"sub": os.getenv("WEB_PUSH_SUBJECT", "https://sourcera.147.189.171.211.sslip.io")}, ttl=86400, timeout=8)
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in {404, 410}:
                sub.active = False
                db.commit()
                continue
            raise
        row.sent_to = [*row.sent_to, sub.id]
        db.commit()


class Endpoint(BaseModel):
    endpoint: str = Field(min_length=10, max_length=3000)

    @field_validator("endpoint")
    @classmethod
    def push_service_only(cls, value):
        url = urlsplit(value)
        allowed = ("push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com", "notify.windows.com")
        host = (url.hostname or "").lower()
        if url.scheme != "https" or url.username or url.password or url.port not in {None, 443} or not any(host == h or host.endswith("." + h) for h in allowed):
            raise ValueError("Unsupported browser push service")
        return value

class Subscribe(Endpoint):
    keys: dict[str, str]

    @field_validator("keys")
    @classmethod
    def valid_keys(cls, keys):
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            if set(keys) != {"p256dh", "auth"} or any(len(v) > 200 for v in keys.values()):
                raise ValueError()
            public = base64.urlsafe_b64decode(keys["p256dh"] + "=" * (-len(keys["p256dh"]) % 4))
            auth = base64.urlsafe_b64decode(keys["auth"] + "=" * (-len(keys["auth"]) % 4))
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
            if len(auth) != 16:
                raise ValueError()
        except (ValueError, KeyError):
            raise ValueError("Invalid push subscription keys")
        return {"p256dh": keys["p256dh"], "auth": keys["auth"]}

router = APIRouter()

@router.get("/notifications/settings")
def config(user=Depends(current_user)):
    on = enabled("WEB_PUSH_ENABLED", True)
    return {"available": on, "public_key": vapid_keys()[1] if on else None}

@router.post("/notifications/subscriptions", status_code=201)
def subscribe(body: Subscribe, db=Depends(get_db), user=Depends(current_user)):
    if not enabled("WEB_PUSH_ENABLED", True):
        raise HTTPException(503, "Browser notifications are unavailable")
    row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint).with_for_update())
    if not row:
        row = PushSubscription(user_id=user.id, endpoint=body.endpoint, keys=body.keys)
        db.add(row)
    row.user_id, row.keys, row.active = user.id, body.keys, True
    db.commit()
    return {"enabled": True}

@router.delete("/notifications/subscriptions", status_code=204)
def unsubscribe(body: Endpoint, db=Depends(get_db), user=Depends(current_user)):
    row = db.scalar(select(PushSubscription).where(PushSubscription.user_id == user.id, PushSubscription.endpoint == body.endpoint))
    if row:
        row.active = False
        db.commit()

@router.get("/notifications")
def inbox(db=Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(ListenerNotification).where(ListenerNotification.user_id == user.id).order_by(ListenerNotification.created_at.desc()).limit(50)).all()
    return [dict(id=n.id, title=n.title, url="/briefings/" + n.briefing_id if n.briefing_id else "/", read=n.read, created_at=n.created_at) for n in rows]

@router.post("/notifications/{notification_id}/read", status_code=204)
def mark_read(notification_id: str, db=Depends(get_db), user=Depends(current_user)):
    row = db.scalar(select(ListenerNotification).where(ListenerNotification.user_id == user.id, ListenerNotification.id == notification_id))
    if not row:
        raise HTTPException(404, "Notification not found")
    row.read = True
    db.commit()

@router.post("/notifications/subscriptions/status")
def subscription_status(body: Endpoint, db=Depends(get_db), user=Depends(current_user)):
    row = db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user.id, PushSubscription.endpoint == body.endpoint, PushSubscription.active.is_(True)))
    return {"enabled": bool(row)}

@router.post("/notifications/test", status_code=202)
def test_notification(db=Depends(get_db), user=Depends(current_user)):
    from .jobs import queue_record
    if not db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user.id, PushSubscription.active.is_(True))):
        raise HTTPException(422, "Enable notifications on this device first")
    row = ListenerNotification(user_id=user.id, title="Notifications are on")
    db.add(row)
    db.flush()
    queue_record(db, "notification", row.id)
    db.commit()
    return {"queued": True}
