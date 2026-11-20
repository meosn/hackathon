"""Convert Forex Factory's Latest Stories and Hot Stories to ingestion records."""

import re
from datetime import UTC, datetime, timedelta, tzinfo
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pydantic import ValidationError

from .adapters import InputArticle

FOREX_URL = "https://www.forexfactory.com/news"
RELATIVE = re.compile(
    r"(\d+)\s*(weeks?|days?|hours?|hrs?|minutes?|mins?|seconds?|secs?)\b", re.I
)
UNITS = dict(w="weeks", d="days", h="hours", m="minutes", s="seconds")


def publication_time(
    value: str, now: datetime, page_timezone: tzinfo
) -> datetime | None:
    if value.casefold().endswith(" ago"):
        parts = RELATIVE.findall(value)
        if parts:
            return now - sum(
                (timedelta(**{UNITS[unit[0].lower()]: int(n)}) for n, unit in parts),
                timedelta(),
            )
    for fmt in ("%b %d, %Y, %I:%M%p", "%B %d, %Y, %I:%M%p"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=page_timezone)
        except ValueError:
            continue
    return None


def parse_news_page(
    html: bytes, now: datetime | None = None, page_timezone: tzinfo = UTC
) -> list[InputArticle]:
    soup = BeautifulSoup(html, "html.parser")
    now = now or datetime.now(UTC)
    articles = {}
    for card in soup.select(".news-block__item, .hot-story"):
        anchor = card.select_one(
            ".news-block__title a[href], a.hot-story__title[href], .hot-story__title a[href]"
        )
        stamp = card.select_one(
            ".news-block__details span[title], .hot-story__details span[title]"
        )
        if not anchor or not stamp:
            continue
        published = publication_time(
            stamp["title"].strip() or stamp.get_text(" ", strip=True),
            now,
            page_timezone,
        )
        if not published:
            continue
        title = anchor.get_text(" ", strip=True)
        excerpt = card.select_one(
            ".hot-story__preview, .hot-story__body, .hot-story__description, "
            ".news-block__body, .news-block__description"
        )
        if excerpt:
            for details in excerpt.select(".news-block__details, .hot-story__details"):
                details.decompose()
        body = (excerpt.get_text(" ", strip=True) if excerpt else "") or title
        try:
            article = InputArticle(
                title=title,
                content=body,
                source="Forex Factory",
                url=urljoin(FOREX_URL, anchor["href"]),
                published_at=published,
                language="en",
            )
        except ValidationError:
            continue
        url = str(article.url)
        previous = articles.get(url)
        if previous is None or (previous.content == previous.title and body != title):
            articles[url] = article
    if not articles:
        raise ValueError("No dated news cards found on the Forex Factory news page")
    return list(articles.values())
