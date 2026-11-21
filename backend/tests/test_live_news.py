from datetime import datetime, UTC, timedelta
from hashlib import sha256
from email.utils import format_datetime
import httpx
from app.news import adapters, analysis
from app.news.adapters import InputArticle
from app.news.models import Story, Article, Source, StoryArticle, IngestionJob
from app.briefing.ranking import recommendations, news_now
from test_listener_workflow import session, listener


def test_feed_preparation_limits_age_count_and_future_items(monkeypatch):
    now = datetime.now(UTC)
    entries = "".join(
        f"<item><title>Report {i}</title><description>A government announced a transport plan.</description><link>https://www.bbc.com/news/{i}</link><pubDate>{format_datetime(now+timedelta(hours=offset))}</pubDate></item>"
        for i, offset in enumerate([-100, -3, -1, 2])
    )
    data = (
        '<rss version="2.0"><channel><title>News</title>' + entries + "</channel></rss>"
    ).encode()
    monkeypatch.setenv("ACTIVE_CORPUS", "live")
    monkeypatch.setenv("RSS_MAX_AGE_HOURS", "48")
    monkeypatch.setenv("RSS_MAX_ARTICLES", "1")
    monkeypatch.setenv("NEWS_ENRICH_FEEDS", "0")
    rows = list(
        adapters.prepared_feed(
            data,
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            publisher="BBC News",
            language="en",
        )
    )
    assert (
        len(rows) == 1 and rows[0].title == "Report 2" and rows[0].source == "BBC News"
    )


def test_public_article_enrichment_preserves_metadata_and_rejects_untrusted_redirects(
    monkeypatch,
):
    row = InputArticle(
        title="A reported policy decision",
        content="The government announced a transport plan.",
        source="BBC News",
        url="https://www.bbc.com/news/public-story",
        published_at=datetime.now(UTC),
        language="en",
    )
    requests = []
    redirect = True
    paragraph = "The government announced a new public transport plan after the parliamentary vote, according to the published council statement."

    def server(request):
        requests.append(str(request.url))
        if redirect:
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<article><nav><p>Ignore this navigation.</p></nav><p>"
            + paragraph
            + "</p><p>A second statement explains the planned timeline for the project and describes how local councils will review the proposals.</p></article>",
        )

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(server), **kw),
    )
    assert adapters.enrich_public_article(row) == row and len(requests) == 1
    redirect = False
    enriched = adapters.enrich_public_article(row)
    assert paragraph in enriched.content and "navigation" not in enriched.content
    assert (
        enriched.url == row.url
        and enriched.published_at == row.published_at
        and enriched.source == row.source
    )


def test_live_recommendations_use_fresh_public_articles_and_ignore_archive_anchor(
    session, monkeypatch
):
    user = listener(session, "live-reader", "en", [])
    now = datetime.now(UTC)
    ids = {}
    for kind in ["dataset", "source"]:
        job = IngestionJob(kind=kind, status="completed")
        source = Source(name=kind + " publisher", is_synthetic=False)
        session.add_all([job, source])
        session.flush()
        story = Story(
            title="Reported parliamentary decision " + kind,
            summary="The parliament approved the transport plan.",
            category="politics",
            importance=0.5,
            urgency=0.3,
            event_at=now - timedelta(days=3),
            updated_at=now,
            is_synthetic=False,
        )
        session.add(story)
        session.flush()
        article = Article(
            job_id=job.id,
            source_id=source.id,
            title=story.title,
            content=story.summary,
            url="https://example.test/" + kind,
            published_at=now - timedelta(minutes=10),
            language="en",
            content_hash=sha256(kind.encode()).hexdigest(),
            is_synthetic=False,
            status="analyzed",
        )
        session.add(article)
        session.flush()
        session.add(StoryArticle(story_id=story.id, article_id=article.id))
        ids[kind] = story.id
    session.commit()
    monkeypatch.setenv("ACTIVE_CORPUS", "live")
    monkeypatch.setenv("NEWS_REFERENCE_TIME", "1999-01-01T00:00:00+00:00")
    assert abs((news_now() - now).total_seconds()) < 10
    rows = recommendations(session, user.id, period="day")
    assert [row["id"] for row in rows] == [ids["source"]]
    explicit = recommendations(
        session, user.id, period="day", selected=[ids["dataset"]]
    )
    assert [row["id"] for row in explicit] == [ids["dataset"]]
    assert "politics" in analysis.classify(
        "Parliament votes in presidential election",
        "The government announced the result.",
    )
    assert "politics" in analysis.classify(
        "Regierung nach der Wahl", "Das Parlament stimmt ab."
    )
    assert "politics" in analysis.classify(
        "Verkiezingen in Nederland", "De regering vormt een nieuw kabinet."
    )
