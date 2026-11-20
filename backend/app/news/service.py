import hashlib
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.news import analysis
from app.news.adapters import (
    clean,
    dataset_path,
    feed_records,
    file_records,
    fixture_records,
)
from app.news.models import (
    Article,
    ArticleEmbedding,
    ClaimEvidence,
    Fact,
    IngestionJob,
    Source,
    SourceDisagreement,
    Story,
    StoryArticle,
    StoryTopic,
)
from app.news.verification import (
    NUMBER,
    canonical,
    comparison_key,
    extract_claims,
    verify_claim,
)


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value):
    return utc(value).isoformat()


def _pipeline_lock(db: Session):
    # Serialize cluster membership + dedup decisions across workers and admin edits.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(85203110)"))


def create_job(db, kind="fixture", locator=None):
    from app.messaging import emit
    from app.news.adapters import validate_feed

    if kind == "dataset":
        dataset_path(locator or "")
    elif kind == "rss":
        validate_feed(locator or "")
    elif kind != "fixture" or locator:
        raise ValueError("Unknown ingestion input")
    job = IngestionJob(kind=kind, locator=locator, status="queued")
    db.add(job)
    db.flush()
    emit(db, "news.ingest.requested", job.id, job.id)
    return job


def _normalize(db, job, records):
    from app.messaging import emit
    from app.usage import record

    _pipeline_lock(db)
    start = monotonic()
    synthetic = job.kind == "fixture"
    for row in records:
        body, title = clean(row.content), clean(row.title)
        if not body or not title:
            raise ValueError("Article has no readable title or content")
        job.received += 1
        digest = hashlib.sha256(body.encode()).hexdigest()
        exists = db.scalar(
            select(Article.id).where(
                Article.content_hash == digest, Article.is_synthetic == synthetic
            )
        )
        if exists:
            job.duplicates += 1
            continue
        source = db.scalar(
            select(Source).where(
                Source.name == row.source, Source.is_synthetic == synthetic
            )
        )
        if not source:
            source = Source(name=row.source, is_synthetic=synthetic)
            db.add(source)
            db.flush()
        article = Article(
            job_id=job.id,
            source_id=source.id,
            external_id=row.external_id,
            title=title,
            content=body,
            url=str(row.url),
            published_at=row.published_at,
            author=row.author,
            language=row.language,
            content_hash=digest,
            is_synthetic=synthetic,
            status="normalized",
        )
        db.add(article)
        db.flush()
        for event in ("news.article.created", "news.article.normalized"):
            emit(db, event, article.id, job.id)
    job.status = "normalized"
    record(
        db,
        "ingestion",
        "normalize-v1",
        seconds=monotonic() - start,
        measured_usd=0,
        scope="dataset",
        reference_id=job.id,
    )


def run_ingestion(db, job_id):
    _pipeline_lock(db)
    job = db.get(IngestionJob, job_id)
    if not job:
        raise ValueError("Unknown ingestion job")
    if job.status in {"normalized", "completed"}:
        return job
    if job.kind == "fixture":
        rows = fixture_records(utc(job.created_at))
    elif job.kind == "dataset":
        rows = file_records(dataset_path(job.locator))
    else:
        rows = feed_records(job.locator)
    _normalize(db, job, rows)
    return job


def new_story(db, article):
    topics = analysis.classify(article.title, article.content)
    importance, urgency = analysis.scores(
        topics, 1, article.title + " " + article.content
    )
    claims = extract_claims(article.content)
    story = Story(
        title=article.title,
        summary=claims[0].text if claims else "",
        category=topics[0],
        importance=importance,
        urgency=urgency,
        event_at=article.published_at,
        updated_at=datetime.now(UTC),
        is_synthetic=article.is_synthetic,
    )
    db.add(story)
    db.flush()
    return story


def _candidate_rows(db, article, vector, model):
    # 72-hour ceiling applies to the first article as well as the candidate.
    low, high = (
        utc(article.published_at) - timedelta(hours=72),
        utc(article.published_at) + timedelta(hours=72),
    )
    stmt = (
        select(Article, ArticleEmbedding, Story)
        .join(ArticleEmbedding, Article.id == ArticleEmbedding.article_id)
        .join(StoryArticle, StoryArticle.article_id == Article.id)
        .join(Story, Story.id == StoryArticle.story_id)
        .where(
            Article.published_at.between(low, high),
            Story.event_at.between(low, high),
            Article.is_synthetic == article.is_synthetic,
            ArticleEmbedding.model == model,
            Story.archived.is_(False),
        )
    )
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.order_by(ArticleEmbedding.embedding.cosine_distance(vector)).limit(
            32
        )
        return db.execute(stmt).all()
    return sorted(
        db.execute(stmt),
        key=lambda row: analysis.cosine(row[1].embedding, vector),
        reverse=True,
    )[:32]


def _near_duplicate(article, other):
    if article.language != other.language:
        return False
    if NUMBER.findall(article.content) != NUMBER.findall(other.content):
        return False

    def shingles(body):
        values = canonical(body)
        return {tuple(values[i : i + 3]) for i in range(len(values) - 2)}

    left, right = shingles(article.content), shingles(other.content)
    return bool(left and right) and len(left & right) / len(left | right) >= 0.76


def _extract_article(db, story, article):
    for claim in extract_claims(article.content):
        fact = db.scalar(
            select(Fact).where(
                Fact.story_id == story.id,
                Fact.text == claim.text,
                Fact.language == article.language,
            )
        )
        if not fact:
            fact = Fact(
                story_id=story.id,
                text=claim.text,
                language=article.language,
                status="supported",
            )
            db.add(fact)
            db.flush()
        db.add(
            ClaimEvidence(
                fact_id=fact.id,
                article_id=article.id,
                excerpt=claim.text,
                start=claim.start,
                end=claim.end,
            )
        )
    db.flush()


def story_articles(db, story_id):
    return db.scalars(
        select(Article)
        .join(StoryArticle, StoryArticle.article_id == Article.id)
        .where(StoryArticle.story_id == story_id)
        .order_by(Article.published_at, Article.created_at, Article.id)
    ).all()


def refresh_story(db, story):
    articles = story_articles(db, story.id)
    if not articles:
        story.archived = True
        return
    # Keep original English headline for multilingual browsing when available.
    lead = next((a for a in articles if a.language == "en"), articles[0])
    facts = db.scalars(
        select(Fact).where(Fact.story_id == story.id).order_by(Fact.created_at, Fact.id)
    ).all()
    by_key = defaultdict(list)
    for fact in facts:
        signature = comparison_key(fact.text, fact.language)
        if signature:
            by_key[(fact.language, signature[0])].append((signature[1], fact))
        if fact.status == "conflicting":
            fact.status = "supported"
    db.execute(
        delete(SourceDisagreement).where(SourceDisagreement.story_id == story.id)
    )
    for members in by_key.values():
        if len({value for value, _ in members}) < 2:
            continue
        ids = [fact.id for _, fact in members]
        sources = db.scalars(
            select(Article.source_id)
            .join(ClaimEvidence, ClaimEvidence.article_id == Article.id)
            .where(ClaimEvidence.fact_id.in_(ids))
            .distinct()
        ).all()
        if len(sources) < 2:
            continue
        for _, fact in members:
            fact.status = "conflicting"
        db.add(
            SourceDisagreement(
                story_id=story.id,
                description="Sources report different values for the same measure.",
                fact_ids=ids,
            )
        )
    topics = analysis.classify(lead.title, lead.content)
    db.execute(delete(StoryTopic).where(StoryTopic.story_id == story.id))
    db.add_all(StoryTopic(story_id=story.id, name=topic) for topic in topics)
    distinct = {a.source_id for a in articles if a.near_duplicate_of is None}
    story.title, story.category = lead.title, topics[0]
    story.importance, story.urgency = analysis.scores(
        topics, len(distinct), lead.title + " " + lead.content
    )
    story.event_at = min(utc(a.published_at) for a in articles)
    story.updated_at = datetime.now(UTC)
    story.summary = next(
        (
            f.text
            for f in facts
            if f.status == "supported" and f.language == lead.language
        ),
        "",
    )
    db.flush()


def _analyze(db, article):
    from app.messaging import emit
    from app.usage import record

    start = monotonic()
    model = analysis.model_name()
    vector = analysis.embed(article.title, article.content)
    record(
        db,
        "embedding",
        model,
        seconds=monotonic() - start,
        measured_usd=0,
        scope="dataset",
        reference_id=article.id,
    )
    db.add(ArticleEmbedding(article_id=article.id, embedding=vector, model=model))
    db.flush()
    fingerprint = analysis.anchors(article.title, article.content)
    threshold = float(os.environ.get("CLUSTER_SIMILARITY", "0.46"))
    story = None
    for other, other_vector, candidate in _candidate_rows(db, article, vector, model):
        score = analysis.cosine(other_vector.embedding, vector)
        if analysis.same_event(
            fingerprint, analysis.anchors(other.title, other.content), score, threshold
        ):
            story = candidate
            if _near_duplicate(article, other):
                article.near_duplicate_of = other.near_duplicate_of or other.id
            break
    event = "news.story.updated" if story else "news.story.created"
    story = story or new_story(db, article)
    db.add(StoryArticle(story_id=story.id, article_id=article.id))
    _extract_article(db, story, article)
    article.status = "analyzed"
    refresh_story(db, story)
    emit(db, event, story.id, article.job_id)


def run_analysis(db, job_id):
    from app.messaging import emit
    from app.usage import record

    _pipeline_lock(db)
    job = db.get(IngestionJob, job_id)
    if not job:
        raise ValueError("Unknown ingestion job")
    if job.status == "completed":
        return job
    if job.status != "normalized":
        raise ValueError("Analysis requires normalized articles")
    start = monotonic()
    articles = db.scalars(
        select(Article)
        .where(Article.job_id == job.id, Article.status == "normalized")
        .order_by(Article.created_at, Article.id)
    ).all()
    for article in articles:
        _analyze(db, article)
        job.analyzed += 1
    job.status = "completed"
    record(
        db,
        "analysis",
        "guarded-events-v1",
        seconds=monotonic() - start,
        measured_usd=0,
        scope="dataset",
        reference_id=job.id,
    )
    emit(db, "news.analysis.completed", job.id, job.id)
    db.flush()
    return job


def import_fixture(db):
    _pipeline_lock(db)
    previous = db.scalar(
        select(IngestionJob)
        .where(IngestionJob.kind == "fixture", IngestionJob.status == "completed")
        .order_by(IngestionJob.created_at)
    )
    if previous:
        return previous
    job = create_job(db)
    run_ingestion(db, job.id)
    return run_analysis(db, job.id)


def ingest_file(db, path):
    """Trusted local CLI entry point. Web requests use the operator filename allowlist."""
    job = IngestionJob(kind="dataset", locator=Path(path).name, status="queued")
    db.add(job)
    db.flush()
    _normalize(db, job, file_records(Path(path)))
    return run_analysis(db, job.id)


def stats(db):
    def count(table, *conditions):
        return (
            db.scalar(select(func.count()).select_from(table).where(*conditions)) or 0
        )

    return dict(
        articles=count(Article),
        duplicates=db.scalar(select(func.sum(IngestionJob.duplicates))) or 0,
        stories=count(Story, Story.archived.is_(False)),
        verified_claims=count(Fact, Fact.status == "supported"),
        conflicting_claims=count(Fact, Fact.status == "conflicting"),
        near_duplicates=count(Article, Article.near_duplicate_of.is_not(None)),
    )


def summaries(db, stories):
    if not stories:
        return []
    ids = [s.id for s in stories]
    grouped, topics = defaultdict(list), defaultdict(list)
    for s_id, src, lang in db.execute(
        select(StoryArticle.story_id, Article.source_id, Article.language)
        .join(Article, Article.id == StoryArticle.article_id)
        .where(StoryArticle.story_id.in_(ids))
    ):
        grouped[s_id].append((src, lang))
    for s_id, topic in db.execute(
        select(StoryTopic.story_id, StoryTopic.name)
        .where(StoryTopic.story_id.in_(ids))
        .order_by(StoryTopic.name)
    ):
        topics[s_id].append(topic)
    result = []
    for s in stories:
        rows = grouped[s.id]
        sources = sorted({src for src, _ in rows})
        result.append(
            dict(
                id=s.id,
                title=s.title,
                summary=s.summary,
                category=s.category,
                topics=topics[s.id],
                importance=s.importance,
                urgency=s.urgency,
                event_at=iso(s.event_at),
                updated_at=iso(s.updated_at),
                source_count=len(sources),
                article_count=len(rows),
                languages=sorted({lang for _, lang in rows}),
                source_ids=sources,
                is_synthetic=s.is_synthetic,
            )
        )
    return result


def story_list(db):
    rows = db.scalars(
        select(Story)
        .where(Story.archived.is_(False))
        .order_by(Story.event_at.desc(), Story.id)
    ).all()
    return summaries(db, rows)


def article_view(article, source):
    return dict(
        id=article.id,
        title=article.title,
        source_id=source.id,
        source_name=source.name,
        url=article.url,
        language=article.language,
        published_at=iso(article.published_at),
        is_synthetic=article.is_synthetic,
        author=article.author,
        near_duplicate_of=article.near_duplicate_of,
    )


def story_detail(db, story_id):
    story = db.get(Story, story_id)
    if not story:
        return None
    view = summaries(db, [story])[0]
    rows = db.execute(
        select(Article, Source)
        .join(Source, Source.id == Article.source_id)
        .join(StoryArticle, StoryArticle.article_id == Article.id)
        .where(StoryArticle.story_id == story_id)
        .order_by(Article.published_at, Article.id)
    ).all()
    view["articles"] = [article_view(a, s) for a, s in rows]
    articles = {a.id: (a, s) for a, s in rows}
    facts = db.scalars(
        select(Fact).where(Fact.story_id == story_id).order_by(Fact.created_at, Fact.id)
    ).all()
    evidence = defaultdict(list)
    for e in db.scalars(
        select(ClaimEvidence)
        .where(ClaimEvidence.fact_id.in_([f.id for f in facts]))
        .order_by(ClaimEvidence.article_id, ClaimEvidence.start)
    ):
        if e.article_id not in articles:
            continue
        a, s = articles[e.article_id]
        evidence[e.fact_id].append(
            dict(
                article_id=a.id,
                source_id=s.id,
                source_name=s.name,
                url=a.url,
                excerpt=e.excerpt,
                start=e.start,
                end=e.end,
                is_synthetic=a.is_synthetic,
            )
        )
    view["facts"] = [
        dict(
            id=f.id,
            text=f.text,
            status=f.status,
            contradiction=f.status == "conflicting",
            language=f.language,
            evidence=evidence[f.id],
        )
        for f in facts
    ]
    view["disagreements"] = [
        dict(id=d.id, description=d.description, fact_ids=d.fact_ids)
        for d in db.scalars(
            select(SourceDisagreement).where(SourceDisagreement.story_id == story_id)
        )
    ]
    return view


def verify_segment(db, text, claim_ids, source_article_ids, allow_conflict=False):
    """Revalidate each supplied citation against stored article bytes before rendering."""
    if len(claim_ids) != 1 or not source_article_ids:
        return False
    fact = db.get(Fact, claim_ids[0])
    if not fact or fact.status not in (
        {"supported", "conflicting"} if allow_conflict else {"supported"}
    ):
        return False
    if not verify_claim(text, [fact.text]):
        return False
    evidence = db.execute(
        select(ClaimEvidence, Article)
        .join(Article, Article.id == ClaimEvidence.article_id)
        .where(
            ClaimEvidence.fact_id == fact.id,
            ClaimEvidence.article_id.in_(source_article_ids),
        )
    ).all()
    supported = {
        a.id
        for e, a in evidence
        if a.url
        and 0 <= e.start < e.end <= len(a.content)
        and a.content[e.start : e.end] == e.excerpt
        and verify_claim(text, [e.excerpt])
    }
    return supported == set(source_article_ids)


def move_articles(db, origin, target, article_ids):
    from app.briefing.models import BriefingItem, ConversationMessage

    _pipeline_lock(db)
    if (
        origin.archived
        or target.archived
        or origin.id == target.id
        or origin.is_synthetic != target.is_synthetic
    ):
        raise ValueError("Select distinct active stories of the same provenance")
    for model in (BriefingItem, ConversationMessage):
        if db.scalar(
            select(model.id).where(model.story_id.in_([origin.id, target.id])).limit(1)
        ):
            raise ValueError(
                "Stories cited by a briefing or conversation retain their original membership"
            )
    valid_ids = {a.id for a in story_articles(db, origin.id)}
    if not article_ids or not set(article_ids) <= valid_ids:
        raise ValueError("Selected articles must belong to the origin story")
    for fact in db.scalars(select(Fact).where(Fact.story_id == origin.id)).all():
        refs = db.scalars(
            select(ClaimEvidence).where(ClaimEvidence.fact_id == fact.id)
        ).all()
        moving = [ref for ref in refs if ref.article_id in article_ids]
        if not moving:
            continue
        if len(moving) == len(refs):
            fact.story_id = target.id
        else:
            copied = Fact(
                story_id=target.id,
                text=fact.text,
                language=fact.language,
                status="supported",
            )
            db.add(copied)
            db.flush()
            for ref in moving:
                ref.fact_id = copied.id
    for assoc in db.scalars(
        select(StoryArticle).where(StoryArticle.article_id.in_(article_ids))
    ):
        assoc.story_id = target.id
    db.flush()
    refresh_story(db, origin)
    refresh_story(db, target)
