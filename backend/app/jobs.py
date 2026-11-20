"""Dispatch, bounded retries, local execution and time-zone-aware schedule discovery."""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from celery import Celery
from kombu import Exchange, Queue
from sqlalchemy import DateTime, String, UniqueConstraint, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column
from .config import settings
from .db import Record, SessionLocal, engine, utcnow

log = logging.getLogger("sourcera.workers")
local_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sourcera-local")
KINDS = ("ingestion", "analysis", "briefing", "voice")
tasks = Celery("sourcera", broker=settings.broker_url)
task_exchange = Exchange("sourcera.tasks", type="direct", durable=True)
tasks.conf.update(
    task_queues=[
        Queue(
            f"tasks.{k}",
            exchange=task_exchange,
            routing_key=k,
            durable=True,
            queue_arguments={"x-dead-letter-exchange": "domain.dead"},
        )
        for k in KINDS
    ],
    task_default_queue="tasks.ingestion",
    task_default_exchange="sourcera.tasks",
    task_default_routing_key="ingestion",
    task_create_missing_queues=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_ignore_result=True,
    broker_transport_options={"confirm_publish": True},
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    worker_hijack_root_logger=False,
    beat_schedule={
        "dispatch-and-deliver": {
            "task": "sourcera.tick",
            "schedule": 15.0,
            "options": {"queue": "tasks.ingestion", "routing_key": "ingestion"},
        }
    },
)


class ProcessingJob(Record):
    __tablename__ = "processing_jobs"
    __table_args__ = (UniqueConstraint("kind", "entity_id"),)
    kind: Mapped[str] = mapped_column(String(24))
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


def queue_record(db, kind, id):
    q = select(ProcessingJob).where(
        ProcessingJob.kind == kind, ProcessingJob.entity_id == id
    )
    row = db.scalar(q)
    if not row:
        try:
            with db.begin_nested():
                row = ProcessingJob(kind=kind, entity_id=id)
                db.add(row)
                db.flush()
        except IntegrityError:
            row = db.scalars(q).one()
    return row


def enqueue(kind, id):
    with SessionLocal.begin() as db:
        job = queue_record(db, kind, id)
        job_id = job.id
    publish(job_id)


def enqueue_briefing(id):
    enqueue("briefing", id)


def enqueue_ingestion(id):
    enqueue("ingestion", id)


def publish(job_id):
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.status == "pending",
                ProcessingJob.next_attempt <= utcnow(),
            )
            .with_for_update(skip_locked=True)
        )
        if not job:
            return
        # A lease also recovers a crash between the DB commit and broker confirmation.
        job.next_attempt = utcnow() + timedelta(minutes=5)
        kind = job.kind
    if settings.job_mode == "local":
        local_pool.submit(execute, job_id)
    else:
        try:
            tasks.send_task(
                "sourcera.work",
                args=[job_id],
                queue=f"tasks.{kind}",
                routing_key=kind,
                retry=False,
            )
        except Exception as exc:
            log.warning(
                "task_publish_deferred", extra={"error_type": type(exc).__name__}
            )
            with SessionLocal.begin() as db:
                db.get(ProcessingJob, job_id).next_attempt = utcnow() + timedelta(
                    seconds=15
                )


def execute(id):
    # Session-level advisory lock spans service commits and releases on worker death.
    with engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            locked = conn.scalar(
                text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                {"key": id},
            )
            conn.commit()
            if not locked:
                return
        try:
            with Session(bind=conn, expire_on_commit=False) as db:
                _execute(db, id)
        finally:
            if conn.dialect.name == "postgresql":
                conn.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                    {"key": id},
                )
                conn.commit()


def _execute(db, id):
    from .briefing import service as briefing
    from .news import service as news
    from .news.models import IngestionJob

    job = db.get(ProcessingJob, id)
    if not job or job.status != "pending":
        return
    kind, entity = job.kind, job.entity_id
    job.attempts += 1
    db.commit()
    try:
        if kind == "ingestion":
            news.run_ingestion(db, entity)
        elif kind == "analysis":
            news.run_analysis(db, entity)
        elif kind == "briefing":
            briefing.generate_script(db, entity)
        else:
            briefing.synthesize_briefing(db, entity)
        next_kind = {"ingestion": "analysis", "briefing": "voice"}.get(kind)
        next_job = queue_record(db, next_kind, entity).id if next_kind else None
        job.status = "done"
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning(
            "stage_failed", extra={"stage": kind, "error_type": type(exc).__name__}
        )
        if job.attempts >= 4 or type(exc).__name__ in {
            "VerificationError",
            "PublicationBlocked",
            "ValueError",
        }:
            job.status = "dead"
            if kind in {"briefing", "voice"}:
                briefing.fail_briefing(db, entity, exc)
            else:
                row = db.get(IngestionJob, entity)
                if row:
                    row.status, row.error = (
                        "failed",
                        "Import failed. Check the input and service configuration.",
                    )
                    from .messaging import emit

                    emit(db, "news.article.failed", entity, entity)
        else:
            job.next_attempt = utcnow() + timedelta(seconds=2**job.attempts)
        db.commit()
        return
    if next_job:
        publish(next_job)


@tasks.task(name="sourcera.work")
def work(job_id):
    execute(job_id)


def discover(db, now):
    from .accounts import Schedule

    schedules = db.scalars(
        select(Schedule)
        .where(Schedule.enabled.is_(True))
        .with_for_update(skip_locked=True)
    ).all()
    for s in schedules:
        local = now.astimezone(ZoneInfo(s.timezone))
        if s.last_local_date == local.date() or local.strftime("%H:%M") < s.time:
            continue
        s.last_local_date = local.date()
        from .briefing.daily import ensure_daily

        briefing = ensure_daily(db, s.user_id, now)
        queue_record(db, "briefing", briefing.id)
    db.commit()


def recover():
    from .news.models import IngestionJob
    from .briefing.models import Briefing

    with SessionLocal.begin() as db:
        for model, kind in ((IngestionJob, "ingestion"), (Briefing, "briefing")):
            existing = (
                select(ProcessingJob.id)
                .where(ProcessingJob.kind == kind, ProcessingJob.entity_id == model.id)
                .exists()
            )
            for entity in db.scalars(
                select(model.id).where(model.status == "queued", ~existing).limit(100)
            ):
                queue_record(db, kind, entity)
        pending = db.scalars(
            select(ProcessingJob.id)
            .where(
                ProcessingJob.status == "pending",
                ProcessingJob.next_attempt <= utcnow(),
            )
            .limit(100)
        ).all()
    for id in pending:
        publish(id)


def discover_news(db, now):
    from .news.adapters import SOURCE_IDS, config_list, validate_feed
    from .news.service import create_job
    from .news.models import IngestionJob

    configured = []
    for source_id in config_list("NEWS_SOURCES"):
        if source_id in SOURCE_IDS:
            configured.append(("source", source_id))
        else:
            log.warning("Unknown NEWS_SOURCES entry: %s", source_id)
    for url in config_list("RSS_FEED_URLS"):
        try:
            validate_feed(url)
        except ValueError:
            log.warning("Ignoring an invalid RSS_FEED_URLS entry")
        else:
            configured.append(("rss", url))

    if not configured:
        return
    interval = max(1, int(os.getenv("RSS_INTERVAL_MINUTES", "60")))
    for kind, locator in configured:
        recent = db.scalar(
            select(IngestionJob.id)
            .where(
                IngestionJob.kind == kind,
                IngestionJob.locator == locator,
                IngestionJob.created_at > now - timedelta(minutes=interval),
            )
            .limit(1)
        )
        if not recent:
            job = create_job(db, kind=kind, locator=locator)
            queue_record(db, "ingestion", job.id)
    db.commit()


@tasks.task(name="sourcera.tick")
def tick():
    with SessionLocal() as db:
        if settings.demo_mode:
            from .news.models import Story

            if db.scalar(select(Story.id).limit(1)):
                from .briefing.daily import seed_templates

                seed_templates(db)
                db.commit()
        discover(db, utcnow())
        discover_news(db, utcnow())
    recover()
    if settings.job_mode == "celery":
        from .messaging import relay

        relay()
