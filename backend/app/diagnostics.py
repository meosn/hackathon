"""Read-only checks against the configured database, broker and gateway environment."""

from sqlalchemy import func, select, text
from .db import SessionLocal
from .messaging import Outbox, Receipt
from .jobs import ProcessingJob


def diagnostics():
    from .briefing.models import Briefing, GeneratedAudio
    from .main import ready
    from .config import settings

    report = {"readiness": ready(), "task_mode": settings.job_mode}
    with SessionLocal() as db:
        report["migration"] = db.scalar(text("select version_num from alembic_version"))
        if db.get_bind().dialect.name == "postgresql":
            report["pgvector"] = db.scalar(
                text("select extversion from pg_extension where extname='vector'")
            )
            report["vector_index"] = db.scalar(
                text(
                    "select indexname from pg_indexes where indexname='ix_article_embeddings_cosine'"
                )
            )
        for key, table, cols in (
            ("outbox", Outbox, [Outbox.status]),
            ("receipts", Receipt, [Receipt.routing_key]),
            ("work", ProcessingJob, [ProcessingJob.kind, ProcessingJob.status]),
            ("briefings", Briefing, [Briefing.status]),
        ):
            rows = db.execute(
                select(*cols, func.count()).select_from(table).group_by(*cols)
            )
            report[key] = {"/".join(row[:-1]): row[-1] for row in rows}
        report["audio_objects"] = db.scalar(
            select(func.count()).select_from(GeneratedAudio)
        )
    return report
