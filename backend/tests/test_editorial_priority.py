import pytest
from app.news.editorial import assess, assess_story
from app.news.models import Story
from sqlalchemy import select
from test_listener_workflow import session


@pytest.mark.parametrize('title',[
    'ECB cuts interest rates after policy decision',
    'EZB senkt den Leitzins nach Beschluss',
    'Centrale bank verlaagt rente na besluit',
])
def test_policy_decisions_outrank_stock_promotions(title):
    policy = assess(title, title, 2)
    promotion = assess('Top stocks to buy now', 'Markets and finance news.', 10)
    assert policy['importance'] > promotion['importance']
    assert policy['urgency'] > promotion['urgency']
    assert 'Central bank policy decision' in policy['reasons']


def test_footer_and_repetition_do_not_create_urgency():
    ordinary = 'Company presents its new website. ' * 100
    result = assess('Company presents a website', ordinary + 'Emergency evacuation. Central bank cuts interest rates.', 1)
    assert result['importance'] == .25
    assert result['urgency'] == .12
    assert assess('Company presents a website', ordinary, 100)['importance'] <= .37


def test_forecasts_have_lower_urgency_than_reported_emergencies():
    actual = assess('Flood evacuation ordered nationwide', 'Thousands people evacuated.', 3)
    forecast = assess('Could flood evacuation be needed?', 'Forecast warns of possible flooding.', 3)
    assert actual['urgency'] > forecast['urgency']
    assert actual['importance'] > forecast['importance']
    assert 0 <= actual['importance'] <= 1


def test_current_story_scores_can_be_reproduced_without_model_calls(session, monkeypatch):
    from app.news.service import run_analysis
    from app.news.models import IngestionJob
    job = session.scalars(select(IngestionJob)).first()
    run_analysis(session, job.id)
    story = session.scalars(select(Story)).first()
    result = assess_story(session, story)
    assert (story.importance, story.urgency) == (result['importance'], result['urgency'])
    assert result['version'] == 'editorial-v2'


@pytest.mark.parametrize('left,right,distinct', [
    ('Arden reports Q1 2026 earnings', 'Arden reports Q2 2026 earnings', True),
    ('Arden reports first quarter earnings', 'Arden reports second quarter earnings', True),
    ('Arden reports Q1 2025 earnings', 'Arden reports Q1 2026 earnings', True),
    ('Arden reports Q1 profit of 20 million', 'Arden reports Q1 profit of 30 million', False),
    ('Arden reports earnings', 'Arden reports Q1 earnings', False),
])
def test_explicit_reporting_period_boundaries(left, right, distinct):
    from app.news.analysis import distinct_reporting_periods
    assert distinct_reporting_periods(left, right) is distinct


def test_selection_explains_score_and_critical_override():
    from datetime import UTC, datetime
    from app.briefing.ranking import ranked
    now = datetime.now(UTC)
    stories = [dict(id=str(i), title='Update', summary='', category='finance' if i < 3 else 'climate',
                    topics=[], source_ids=['s'], event_at=now, importance=.5 if i < 3 else .9,
                    urgency=.1 if i < 3 else .95) for i in range(4)]
    result = ranked(stories, {'interests': ['finance']}, now=now)
    assert result[2]['id'] == '3'
    assert result[2]['selection']['adjustments'] == ['Reserved a top-three slot for a critical event']
    explanation = result[0]['selection']
    assert sum(f['contribution'] for f in explanation['factors'].values()) == pytest.approx(explanation['score'])
    assert 'Matches your selected interests' in explanation['reasons']
    assert 'selection' not in stories[0]
    assert not ranked(stories, {'excluded_sources': ['s']}, now=now)


def test_jury_inventory_checks_exact_spans_and_detects_drift(session):
    from app.news.audit import report
    from app.news.models import ClaimEvidence
    baseline = report(session)
    assert baseline['counts']['evidence_spans'] > 0
    assert baseline['counts']['invalid_evidence_spans'] == 0
    assert baseline['counts']['priority_drift'] == 0
    assert baseline['acceptance']['official_answer_key'] == 'not supplied'
    session.scalars(select(ClaimEvidence)).first().start += 1
    session.scalars(select(Story)).first().importance = 0
    session.flush()
    changed = report(session)
    assert changed['counts']['invalid_evidence_spans'] == 1
    assert changed['counts']['priority_drift'] == 1
