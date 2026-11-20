from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Record

Json = JSON().with_variant(JSONB(), "postgresql")


class Source(Record):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("name", "is_synthetic"),)
    name: Mapped[str] = mapped_column(String(180))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class IngestionJob(Record):
    __tablename__ = "ingestion_jobs"
    kind: Mapped[str] = mapped_column(String(24))
    locator: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    received: Mapped[int] = mapped_column(default=0)
    duplicates: Mapped[int] = mapped_column(default=0)
    analyzed: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(200))


class Article(Record):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("content_hash", "is_synthetic"),
        Index("ix_articles_published_status", "published_at", "status"),
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("ingestion_jobs.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(250))
    title: Mapped[str] = mapped_column(String(800))
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    author: Mapped[str | None] = mapped_column(String(240))
    language: Mapped[str] = mapped_column(String(12), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(24), default="normalized")
    near_duplicate_of: Mapped[str | None] = mapped_column(ForeignKey("articles.id"))


class Story(Record):
    __tablename__ = "stories"
    title: Mapped[str] = mapped_column(String(800))
    summary: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80), index=True)
    importance: Mapped[float] = mapped_column(Float, index=True)
    urgency: Mapped[float] = mapped_column(Float)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class StoryArticle(Record):
    __tablename__ = "story_articles"
    story_id: Mapped[str] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), index=True
    )
    article_id: Mapped[str] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), unique=True
    )


class StoryTopic(Record):
    __tablename__ = "story_topics"
    __table_args__ = (UniqueConstraint("story_id", "name"),)
    story_id: Mapped[str] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), index=True)


class ArticleEmbedding(Record):
    __tablename__ = "article_embeddings"
    __table_args__ = (
        Index(
            "ix_article_embeddings_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )
    article_id: Mapped[str] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), unique=True
    )
    model: Mapped[str] = mapped_column(String(180))
    embedding: Mapped[list] = mapped_column(Vector(384).with_variant(JSON(), "sqlite"))


class Fact(Record):
    __tablename__ = "facts"
    story_id: Mapped[str] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(24), default="supported", index=True)


class ClaimEvidence(Record):
    __tablename__ = "claim_evidence"
    __table_args__ = (UniqueConstraint("fact_id", "article_id", "start"),)
    fact_id: Mapped[str] = mapped_column(
        ForeignKey("facts.id", ondelete="CASCADE"), index=True
    )
    article_id: Mapped[str] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    excerpt: Mapped[str] = mapped_column(Text)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)


class SourceDisagreement(Record):
    __tablename__ = "source_disagreements"
    story_id: Mapped[str] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    fact_ids: Mapped[list[str]] = mapped_column(Json)
