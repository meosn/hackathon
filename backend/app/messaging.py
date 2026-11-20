"""A transactional domain-event outbox and an idempotent operational projection."""

from datetime import datetime, timedelta
from kombu import Connection, Exchange, Producer, Queue
from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column
from .config import settings
from .db import Record, SessionLocal, utcnow

EVENTS = {
    "news": (
        "ingest.requested",
        "article.created",
        "article.normalized",
        "article.failed",
        "story.created",
        "story.updated",
        "analysis.completed",
    ),
    "briefing": (
        "requested",
        "generation.started",
        "script.ready",
        "verification.failed",
        "audio.requested",
        "audio.ready",
        "completed",
        "failed",
    ),
    "voice": (
        "transcription.requested",
        "transcription.completed",
        "synthesis.requested",
        "synthesis.completed",
    ),
}
KEYS = {
    f"{family}.{suffix}" for family, suffixes in EVENTS.items() for suffix in suffixes
}
dead = Exchange("domain.dead", type="topic", durable=True)
exchanges = {
    group: Exchange(f"{group}.events", type="topic", durable=True) for group in EVENTS
}
queues = {
    g: Queue(
        f"domain.{g}.audit",
        exchange=x,
        routing_key=f"{g}.#",
        durable=True,
        queue_arguments={"x-dead-letter-exchange": "domain.dead"},
    )
    for g, x in exchanges.items()
}
dead_queue = Queue("domain.dead.letters", exchange=dead, routing_key="#", durable=True)


class Outbox(Record):
    __tablename__ = "event_outbox"
    routing_key: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(80))
    correlation_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Receipt(Record):
    __tablename__ = "event_receipts"
    routing_key: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    correlation_id: Mapped[str] = mapped_column(String(80))


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    event_id: str
    routing_key: str
    entity_id: str
    correlation_id: str
    timestamp: datetime


def emit(db, routing_key, entity_id, correlation_id=None):
    if routing_key not in KEYS:
        raise ValueError("Unregistered domain event")
    db.add(
        Outbox(
            routing_key=routing_key,
            entity_id=str(entity_id),
            correlation_id=str(correlation_id or entity_id),
        )
    )


def connection():
    return Connection(
        settings.broker_url,
        connect_timeout=3,
        transport_options={"confirm_publish": True},
    )


def topology(channel):
    dead_queue(channel).declare()
    for queue in queues.values():
        queue(channel).declare()


def consume(db, data):
    envelope = Envelope.model_validate(data)
    if envelope.version != 1 or envelope.routing_key not in KEYS:
        raise ValueError("Unsupported event")
    if not db.get(Receipt, envelope.event_id):
        db.add(
            Receipt(
                id=envelope.event_id,
                routing_key=envelope.routing_key,
                entity_id=envelope.entity_id,
                correlation_id=envelope.correlation_id,
            )
        )
    db.flush()


def relay():
    # Acknowledgements, the outbox and receipt uniqueness permit safe replay after a crash.
    with connection() as conn, conn.channel() as channel:
        topology(channel)
        producer = Producer(channel, serializer="json")
        with SessionLocal.begin() as db:
            pending = db.scalars(
                select(Outbox)
                .where(Outbox.status == "pending", Outbox.next_attempt <= utcnow())
                .order_by(Outbox.created_at)
                .limit(100)
                .with_for_update(skip_locked=True)
            ).all()
            for e in pending:
                data = {
                    "version": 1,
                    "event_id": e.id,
                    "routing_key": e.routing_key,
                    "entity_id": e.entity_id,
                    "correlation_id": e.correlation_id,
                    "timestamp": e.created_at.isoformat(),
                }
                try:
                    producer.publish(
                        data,
                        exchange=exchanges[e.routing_key.split(".")[0]],
                        routing_key=e.routing_key,
                        delivery_mode=2,
                        mandatory=True,
                        correlation_id=e.correlation_id,
                    )
                except Exception:
                    e.attempts += 1
                    e.status = "dead" if e.attempts >= 8 else "pending"
                    e.next_attempt = utcnow() + timedelta(
                        seconds=min(300, 2**e.attempts)
                    )
                    break
                e.status = "sent"
        for queue in queues.values():
            bound = queue(channel)
            for _ in range(100):
                message = bound.get(no_ack=False, accept=["json"])
                if message is None:
                    break
                try:
                    with SessionLocal.begin() as db:
                        consume(db, message.payload)
                except ValueError:
                    message.reject(requeue=False)
                else:
                    message.ack()
