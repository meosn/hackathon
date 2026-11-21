"""Observed provider activity and explicit pricing assumptions, recorded transactionally."""

import os
from sqlalchemy import Float, ForeignKey, String, case, func, select
from sqlalchemy.orm import Mapped, mapped_column
from .db import Record


class ModelUsage(Record):
    __tablename__ = "model_usage"
    stage: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(240))
    scope: Mapped[str] = mapped_column(String(24))
    reference_id: Mapped[str | None] = mapped_column(String(120), index=True)
    calls: Mapped[int]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    characters: Mapped[int]
    seconds: Mapped[float] = mapped_column(Float)


class CostEvent(Record):
    __tablename__ = "cost_events"
    usage_id: Mapped[str] = mapped_column(
        ForeignKey("model_usage.id", ondelete="CASCADE"), unique=True
    )
    measured_usd: Mapped[float | None] = mapped_column(Float)
    estimated_usd: Mapped[float] = mapped_column(Float)


def record(
    db,
    stage,
    model,
    *,
    calls=1,
    input_tokens=0,
    output_tokens=0,
    characters=0,
    seconds=0,
    measured_usd=None,
    estimated_usd=0,
    scope="listener",
    reference_id=None,
):
    row = ModelUsage(
        stage=stage,
        model=model,
        scope=scope,
        reference_id=reference_id,
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        characters=characters,
        seconds=seconds,
    )
    db.add(row)
    db.flush()
    # Operator-supplied unit prices are estimates, never vendor receipts.
    if not estimated_usd and measured_usd is None:
        estimated_usd = (
            input_tokens * float(os.getenv("LLM_INPUT_USD_PER_M", 0))
            + output_tokens * float(os.getenv("LLM_OUTPUT_USD_PER_M", 0))
            + characters * float(os.getenv("TTS_USD_PER_M_CHARS", 0))
        ) / 1_000_000
    db.add(
        CostEvent(
            usage_id=row.id, measured_usd=measured_usd, estimated_usd=estimated_usd
        )
    )
    return row.id


def costs(db):
    from .news.service import stats
    from .briefing.models import Briefing

    result = stats(db)
    result["processed_records"] = result["articles"] + result["duplicates"]
    hourly = max(0.0, float(os.getenv("COMPUTE_USD_PER_HOUR", "0.04")))
    # Embedding time is inside analysis; script verification includes the model wait.
    timed = ("ingestion", "analysis", "verification", "tts", "stt", "web_research")
    completed = select(Briefing.id).where(Briefing.status == "completed")
    unknown = case(
        (
            (CostEvent.measured_usd.is_(None))
            & (CostEvent.estimated_usd == 0)
            & ModelUsage.stage.in_(("tts", "stt", "llm", "web_research")),
            1,
        ),
        else_=0,
    )
    query = (
        select(
            ModelUsage.scope,
            ModelUsage.stage,
            func.sum(ModelUsage.calls),
            func.sum(ModelUsage.input_tokens),
            func.sum(ModelUsage.output_tokens),
            func.sum(ModelUsage.characters),
            func.sum(ModelUsage.seconds),
            func.sum(CostEvent.measured_usd),
            func.sum(CostEvent.estimated_usd),
            func.sum(unknown),
        )
        .join(CostEvent)
        .group_by(ModelUsage.scope, ModelUsage.stage)
    )
    if os.getenv("ACTIVE_CORPUS") in {"licensed", "live"}:
        from .news.models import Article, IngestionJob, Story

        references = (
            select(IngestionJob.id)
            .where(IngestionJob.kind != "fixture")
            .union(
                select(Article.id).where(Article.is_synthetic.is_(False)),
                select(Story.id).where(Story.is_synthetic.is_(False)),
            )
        )
        query = query.where(
            (ModelUsage.scope != "dataset") | ModelUsage.reference_id.in_(references)
        )
    groups = db.execute(query)
    totals = {
        "llm_calls": 0,
        "embedding_calls": 0,
        "stt_calls": 0,
        "tts_characters": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "measured_usd": 0.0,
        "estimated_usd": 0.0,
        "dataset_usd": 0.0,
        "listener_usd": 0.0,
        "stage_seconds": {},
        "unpriced_events": 0,
    }
    totals["compute_estimate_usd"] = 0.0
    for (
        scope,
        stage,
        calls_,
        inp,
        out,
        chars,
        seconds,
        measured,
        estimated,
        unpriced,
    ) in groups:
        name = stage.lower()
        if "llm" in name or name in {"script", "intent", "discussion"}:
            totals["llm_calls"] += calls_
        if "embed" in name:
            totals["embedding_calls"] += calls_
        if "stt" in name or "transcri" in name:
            totals["stt_calls"] += calls_
        totals["input_tokens"] += inp
        totals["output_tokens"] += out
        totals["tts_characters"] += chars
        totals["stage_seconds"][stage] = round(
            totals["stage_seconds"].get(stage, 0) + seconds, 4
        )
        totals["measured_usd"] += measured or 0
        compute = seconds * hourly / 3600 if stage in timed else 0.0
        totals["compute_estimate_usd"] += compute
        totals["estimated_usd"] += (estimated or 0) + compute
        totals["dataset_usd" if scope == "dataset" else "listener_usd"] += (
            (measured or 0) + (estimated or 0) + compute
        )
        totals["unpriced_events"] += unpriced or 0
    briefings = db.scalar(
        select(func.count()).select_from(Briefing).where(Briefing.status == "completed")
    )
    briefing_spend = (
        db.scalar(
            select(
                func.sum(
                    func.coalesce(CostEvent.measured_usd, 0)
                    + CostEvent.estimated_usd
                    + case(
                        (
                            ModelUsage.stage.in_(timed),
                            ModelUsage.seconds * hourly / 3600,
                        ),
                        else_=0,
                    )
                )
            )
            .select_from(ModelUsage)
            .join(CostEvent)
            .where(ModelUsage.reference_id.in_(completed))
        )
        or 0
    )
    return {
        **result,
        **totals,
        "compute_usd_per_hour": hourly,
        "completed_briefings": briefings,
        "projected_10x_usd": 10 * totals["dataset_usd"] + totals["listener_usd"],
        "cost_per_story": totals["dataset_usd"] / max(result["stories"], 1),
        "cost_per_briefing": briefing_spend / max(briefings, 1),
        "pricing_note": f"Estimated operations use configured unit prices and observed stage time at USD {hourly:g}/hour. The 10× simulation holds listener demand fixed. Unpriced provider calls, idle capacity and storage are excluded.",
    }
