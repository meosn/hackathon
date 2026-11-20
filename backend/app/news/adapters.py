import json
import os
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
)

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic.json"
MAX_BYTES = 15 * 1024 * 1024
RSS_SOURCES = {
    "bloomberg": ("Bloomberg", "https://www.bloomberg.com/feeds/markets/news.rss"),
    "dw": ("DW", "https://rss.dw.com/rdf/rss-en-all"),
    "bbc": ("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
}
SOURCE_IDS = (*RSS_SOURCES, "forex-factory")


class InputArticle(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    title: str = Field(
        min_length=1, max_length=800, validation_alias=AliasChoices("title", "headline")
    )
    content: str = Field(
        min_length=1,
        max_length=250000,
        validation_alias=AliasChoices(
            "content", "body", "full_text", "text", "content_html"
        ),
    )
    source: str = Field(
        min_length=1,
        max_length=180,
        validation_alias=AliasChoices("source", "publisher", "source_name"),
    )
    url: HttpUrl = Field(validation_alias=AliasChoices("url", "original_url", "link"))
    published_at: datetime = Field(
        validation_alias=AliasChoices(
            "published_at", "publication_date", "published", "date"
        )
    )
    author: str | None = Field(None, max_length=240)
    language: str = Field(
        min_length=2, max_length=12, pattern=r"^[a-z]{2,3}(?:-[a-zA-Z]{2,8})?$"
    )
    external_id: str | None = Field(
        None,
        max_length=250,
        validation_alias=AliasChoices("external_id", "id", "article_id"),
    )

    @field_validator("published_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Publication dates require an explicit timezone")
        return value.astimezone(UTC)

    @field_validator("url")
    @classmethod
    def url_without_credentials(cls, value):
        if value.username or value.password:
            raise ValueError("Source links may not contain credentials")
        return value


def clean(value: str) -> str:
    if re.search(r"</?[a-zA-Z]\w*\b[^>]*>", value):
        parser = os.environ.get("NEWS_HTML_PARSER", "beautifulsoup")
        if parser == "scrapling":
            from scrapling import Selector

            value = str(
                Selector(value).get_all_text(
                    separator=" ",
                    strip=True,
                    ignore_tags=("script", "style", "template", "noscript"),
                )
            )
        elif parser == "beautifulsoup":
            soup = BeautifulSoup(value, "html.parser")
            for node in soup(["script", "style", "template", "noscript"]):
                node.decompose()
            value = soup.get_text(" ", strip=True)
        else:
            raise ValueError("Unsupported NEWS_HTML_PARSER")
    return " ".join(unicodedata.normalize("NFC", value).split())


def fixture_records(at: datetime | None = None) -> Iterator[InputArticle]:
    at = at or datetime.now(UTC)
    for row in json.loads(FIXTURE.read_text())["articles"]:
        row["published_at"] = at - timedelta(hours=row.pop("hours_ago"))
        yield InputArticle.model_validate(row)


def dataset_path(filename: str) -> Path:
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        raise ValueError("Provide an allowed dataset filename")
    allowed = {
        v.strip() for v in os.environ.get("DATASET_FILES", "").split(",") if v.strip()
    }
    root = Path(os.environ.get("DATASET_DIR", "/datasets")).resolve()
    path = (root / filename).resolve()
    if path.parent != root or filename not in allowed:
        raise ValueError("Dataset filename is not configured for import")
    if not path.is_file():
        raise ValueError("Dataset file is unavailable")
    return path


def file_records(path: Path) -> Iterator[InputArticle]:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Dataset file exceeds the per-file limit")
    with path.open(encoding="utf-8-sig") as stream:
        if path.suffix.casefold() in {".ndjson", ".jsonl"}:
            for line in stream:
                if line.strip():
                    yield InputArticle.model_validate_json(line)
        elif path.suffix.casefold() == ".json":
            doc = json.load(stream)
            rows = doc["articles"] if isinstance(doc, dict) else doc
            if not isinstance(rows, list):
                raise ValueError("Expected an array of articles")
            for row in rows:
                yield InputArticle.model_validate(row)
        else:
            raise ValueError("Supported file formats are JSON, JSONL and NDJSON")


def config_list(name: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip() for item in os.environ.get(name, "").split(",") if item.strip()
        )
    )


def validate_source(source_id: str):
    if source_id not in SOURCE_IDS or source_id not in config_list("NEWS_SOURCES"):
        raise ValueError("News source is not enabled for ingestion")


def source_records(source_id: str) -> Iterator[InputArticle]:
    validate_source(source_id)
    if source_id == "forex-factory":
        from .forex_factory import FOREX_URL, parse_news_page

        yield from parse_news_page(download(FOREX_URL))
    else:
        publisher, url = RSS_SOURCES[source_id]
        yield from parse_feed(download(url), url, publisher=publisher, language="en")


def validate_feed(url: str):
    parsed = urlsplit(url)
    if (
        url not in config_list("RSS_FEED_URLS")
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Feed URL is not configured for ingestion")


def download(url: str) -> bytes:
    data = bytearray()
    with httpx.stream("GET", url, timeout=12, follow_redirects=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ValueError("News response exceeds the size limit")
    return bytes(data)


def feed_records(url: str) -> Iterator[InputArticle]:
    validate_feed(url)
    yield from parse_feed(download(url), url)


def parse_feed(
    data: bytes, url: str, *, publisher: str | None = None, language: str = "und"
) -> Iterator[InputArticle]:
    import feedparser

    feed = feedparser.parse(data, response_headers={"content-location": url})
    if feed.bozo and not feed.entries:
        raise ValueError("Feed could not be parsed")
    for entry in feed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published or not entry.get("link"):
            continue
        body = (
            entry.content[0].value if entry.get("content") else entry.get("summary", "")
        )
        if not body or not entry.get("title"):
            continue
        lang = entry.get("language") or feed.feed.get("language")
        row = dict(
            source=publisher or feed.feed.get("title") or urlsplit(url).hostname,
            title=entry.title,
            content=body,
            url=entry.link,
            author=entry.get("author"),
            published_at=datetime(*published[:6], tzinfo=UTC),
            language=(lang or language).lower().split("-")[0],
            external_id=entry.get("id"),
        )
        yield InputArticle.model_validate(row)
