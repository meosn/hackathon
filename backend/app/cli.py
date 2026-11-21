"""Operator commands, executed inside the backend container or a local virtualenv."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from .accounts import User, seed_voices
from .config import settings
from .db import SessionLocal, load_models


def bootstrap():
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")
    if os.getenv("AUDIO_STORAGE") == "minio":
        from botocore.exceptions import ClientError
        from .briefing.voice import _bucket

        client, bucket = _bucket()
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
            client.create_bucket(Bucket=bucket)
    if settings.job_mode == "celery":
        from .messaging import connection, topology

        with connection() as broker, broker.channel() as channel:
            topology(channel)
    with SessionLocal.begin() as db:
        seed_voices(db)
        if settings.demo_mode and os.getenv("ACTIVE_CORPUS") not in {
            "licensed",
            "live",
        }:
            from .news.service import create_job, import_fixture
            from .news.models import IngestionJob

            if settings.job_mode == "celery":
                from .jobs import queue_record

                job = db.scalar(
                    select(IngestionJob)
                    .where(IngestionJob.kind == "fixture")
                    .order_by(IngestionJob.created_at)
                    .limit(1)
                )
                if not job:
                    job = create_job(db, kind="fixture")
                    queue_record(db, "ingestion", job.id)
            else:
                job = import_fixture(db)
            print(
                json.dumps(
                    {
                        "fixture": "synthetic",
                        "job_id": job.id,
                        "received": job.received,
                        "duplicates": job.duplicates,
                    }
                )
            )


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="name", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("costs")
    diag = sub.add_parser("diagnostics")
    diag.add_argument("--check-delivery", action="store_true")
    sub.add_parser("openapi")
    sub.add_parser("replay-events")
    imp = sub.add_parser("ingest")
    imp.add_argument("filename")
    sources = sub.add_parser("ingest-source")
    sources.add_argument("source_id")
    forex = sub.add_parser(
        "ingest-forex-html", help="Import a Forex Factory page from stdin"
    )
    forex.add_argument("--captured-at", required=True, type=datetime.fromisoformat)
    sub.add_parser("ingest-all")
    grant = sub.add_parser("grant-admin")
    grant.add_argument("email")
    retry = sub.add_parser("retry")
    retry.add_argument("job_id")
    args = parser.parse_args()
    load_models()
    if args.name == "bootstrap":
        return bootstrap()
    if args.name == "openapi":
        from .main import app

        print(json.dumps(app.openapi(), indent=2))
        return
    with SessionLocal() as db:
        if args.name == "diagnostics":
            from .diagnostics import diagnostics

            report = diagnostics()
            print(json.dumps(report, indent=2))
            required = (
                "news.analysis.completed",
                "briefing.completed",
                "voice.synthesis.completed",
            )
            if args.check_delivery and not all(
                report["receipts"].get(k) for k in required
            ):
                raise SystemExit(1)
        elif args.name == "grant-admin":
            user = db.scalar(select(User).where(User.email == args.email.lower()))
            if not user or user.is_demo:
                parser.error("An existing registered account is required")
            user.is_admin = True
        elif args.name == "costs":
            from .usage import costs

            print(json.dumps(costs(db), indent=2))
        elif args.name == "ingest-all":
            from .news.service import create_job, run_ingestion, run_analysis

            filenames = [
                v.strip()
                for v in os.getenv("DATASET_FILES", "").split(",")
                if v.strip()
            ]
            if not filenames:
                raise ValueError("Configure DATASET_FILES before importing")
            for filename in filenames:
                job = create_job(db, kind="dataset", locator=filename)
                run_ingestion(db, job.id)
                run_analysis(db, job.id)
                db.commit()
                print(
                    json.dumps(
                        {
                            "file": filename,
                            "received": job.received,
                            "duplicates": job.duplicates,
                            "analyzed": job.analyzed,
                        }
                    ),
                    flush=True,
                )
        elif args.name == "ingest-forex-html":
            from .news.adapters import MAX_BYTES
            from .news.service import import_forex_snapshot

            html = sys.stdin.buffer.read(MAX_BYTES + 1)
            if not html or len(html) > MAX_BYTES:
                parser.error("Provide Forex Factory HTML within the 15 MiB limit")
            try:
                job = import_forex_snapshot(db, html, args.captured_at)
            except ValueError as exc:
                parser.error(str(exc))
            db.commit()
            print(
                json.dumps(
                    {
                        "job_id": job.id,
                        "received": job.received,
                        "duplicates": job.duplicates,
                        "analyzed": job.analyzed,
                    }
                )
            )
        elif args.name in {"ingest", "ingest-source"}:
            from .news.service import create_job
            from .jobs import publish, queue_record

            kind, locator = (
                ("dataset", args.filename)
                if args.name == "ingest"
                else ("source", args.source_id)
            )
            try:
                job = create_job(db, kind=kind, locator=locator)
            except ValueError as exc:
                parser.error(str(exc))
            task_id = queue_record(db, "ingestion", job.id).id
            db.commit()
            publish(task_id)
            print(job.id)
        elif args.name == "replay-events":
            from .messaging import Outbox
            from .db import utcnow

            for row in db.scalars(select(Outbox).where(Outbox.status == "dead")):
                row.attempts, row.status, row.next_attempt = 0, "pending", utcnow()
        elif args.name == "retry":
            from .jobs import ProcessingJob, publish
            from .db import utcnow

            job = db.get(ProcessingJob, args.job_id)
            if not job or job.status != "dead":
                parser.error("A terminal processing job ID is required")
            # A retry restarts the failed stage and preserves all previous evidence.
            if job.kind in {"briefing", "voice"}:
                from .briefing.models import Briefing

                b = db.get(Briefing, job.entity_id)
                b.status, b.error = (
                    ("queued" if job.kind == "briefing" else "script_ready"),
                    None,
                )
            elif job.kind in {"analysis", "ingestion"}:
                from .news.models import IngestionJob

                i = db.get(IngestionJob, job.entity_id)
                i.status, i.error = (
                    ("normalized" if job.kind == "analysis" else "queued"),
                    None,
                )
            job.attempts, job.status, job.next_attempt = 0, "pending", utcnow()
            db.commit()
            publish(job.id)
        db.commit()


if __name__ == "__main__":
    main()
