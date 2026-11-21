"""Report coverage separately from corroboration of an individual sourced claim."""

import re
from collections import defaultdict
from sqlalchemy import select, func
from .models import (
    Article,
    Source,
    StoryArticle,
    Fact,
    ClaimEvidence,
    SourceDisagreement,
)
from .verification import canonical, verify_claim


def publisher_family(name):
    name = name.casefold().strip()
    if name.startswith("invezz"):
        return "invezz"
    if name.startswith("international business times") or name.startswith("ibtimes"):
        return "ibtimes"
    return re.sub(r"\s*[-–]\s*(dutch|german|english|french|spanish)$", "", name)


def coverage(db, story_ids, excluded=(), claim_ids=None):
    if not story_ids:
        return {}
    reporters = defaultdict(set)
    articles = {}
    for sid, aid, name, duplicate in db.execute(
        select(
            StoryArticle.story_id, Article.id, Source.name, Article.near_duplicate_of
        )
        .join(Article, Article.id == StoryArticle.article_id)
        .join(Source, Source.id == Article.source_id)
        .where(StoryArticle.story_id.in_(story_ids), Article.source_id.not_in(excluded))
    ):
        # A translated edition of one publisher and a detected reprint are not
        # independent reports, even when their URLs or source IDs are different.
        if duplicate:
            continue
        family = publisher_family(name)
        articles[aid] = family
        reporters[sid].add(family)
    claims = defaultdict(lambda: defaultdict(set))
    multiple = [sid for sid, families in reporters.items() if len(families) >= 2]
    for sid, text, aid, excerpt in db.execute(
        select(
            Fact.story_id, Fact.text, ClaimEvidence.article_id, ClaimEvidence.excerpt
        )
        .join(ClaimEvidence, ClaimEvidence.fact_id == Fact.id)
        .join(Article, Article.id == ClaimEvidence.article_id)
        .where(
            Fact.story_id.in_(multiple),
            Fact.status == "supported",
            Fact.id.in_(claim_ids) if claim_ids is not None else True,
            ClaimEvidence.start >= 0,
            ClaimEvidence.end > ClaimEvidence.start,
            ClaimEvidence.end <= func.length(Article.content),
            func.substr(
                Article.content,
                ClaimEvidence.start + 1,
                ClaimEvidence.end - ClaimEvidence.start,
            )
            == ClaimEvidence.excerpt,
        )
    ):
        if aid in articles and verify_claim(text, [excerpt]):
            claims[sid][canonical(text)].add(articles[aid])
    conflicts = set(
        db.scalars(
            select(SourceDisagreement.story_id).where(
                SourceDisagreement.story_id.in_(story_ids)
            )
        )
    )
    result = {}
    for sid in story_ids:
        count = len(reporters[sid])
        shared = sum(len(families) >= 2 for families in claims[sid].values())
        result[sid] = {
            "publisher_count": count,
            "corroborated_claim_count": shared,
            "coverage_status": (
                "conflicting"
                if sid in conflicts
                else (
                    "corroborated"
                    if shared
                    else "multiple_reports" if count >= 2 else "single_source"
                )
            ),
        }
    return result
