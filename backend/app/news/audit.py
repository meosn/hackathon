"""Read-only, content-free evidence inventory for a reproducible jury review."""
import json
from collections import Counter
from datetime import UTC, datetime
from sqlalchemy import select
from app.db import SessionLocal, load_models
from .models import Story, Fact, ClaimEvidence, Article, IngestionJob
from .editorial import VERSION, assess_story
from .service import story_articles
from .verification import verify_claim
from .analysis import distinct_reporting_periods


def report(db):
    stories = db.scalars(select(Story).where(Story.archived.is_(False)).order_by(Story.id)).all()
    story_ids = [s.id for s in stories]
    evidence = db.execute(
        select(Fact, ClaimEvidence, Article)
        .join(ClaimEvidence, ClaimEvidence.fact_id == Fact.id)
        .join(Article, Article.id == ClaimEvidence.article_id)
        .where(Fact.story_id.in_(story_ids))
    ).all()
    invalid = []
    for fact, span, article in evidence:
        if (article.content[span.start:span.end] != span.excerpt
                or not verify_claim(fact.text, [span.excerpt])):
            invalid.append({'fact_id': fact.id, 'article_id': article.id})
    inventory, period_conflicts = [], []
    for story in stories:
        priority = assess_story(db, story)
        articles = story_articles(db, story.id)
        for i, a in enumerate(articles):
            for b in articles[i + 1:]:
                if distinct_reporting_periods(a.title, b.title):
                    period_conflicts.append({'story_id': story.id, 'article_ids': [a.id, b.id]})
        inventory.append({
            'story_id': story.id, 'synthetic': story.is_synthetic,
            'article_ids': [a.id for a in articles],
            'priority': priority,
            'stored_scores_match': (story.importance, story.urgency) == (priority['importance'], priority['urgency']),
        })
    jobs = db.scalars(select(IngestionJob).order_by(IngestionJob.id)).all()
    return {
        'generated_at': datetime.now(UTC).isoformat(), 'editorial_version': VERSION,
        'scope': 'All active stories, with synthetic flags; IDs and derived signals only, no article text.',
        'acceptance': {'official_profiles': 'not supplied', 'official_answer_key': 'not supplied',
                       'official_releases_comparison': 'not performed',
                       'precision_recall': 'not measured against official labels'},
        'counts': {'active_stories': len(stories), 'evidence_spans': len(evidence),
                   'invalid_evidence_spans': len(invalid),
                   'priority_drift': sum(not s['stored_scores_match'] for s in inventory),
                   'incompatible_period_pairs': len(period_conflicts),
                   'jobs_by_status': dict(Counter(j.status for j in jobs))},
        'invalid_evidence': invalid, 'period_conflicts': period_conflicts, 'stories': inventory,
        'limits': ['Source alignment does not establish truth.',
                   'Period checks detect only explicit title periods; they are not a full clustering quality metric.',
                   'This inventory does not validate realtime speech or official listener fit.'],
    }


def main():
    load_models()
    with SessionLocal() as db:
        print(json.dumps(report(db), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
