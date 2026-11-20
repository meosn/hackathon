"""Initial Sourcera schema, including evidence lineage and event delivery records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "event_outbox",
        sa.Column("routing_key", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("correlation_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_event_outbox_status"), "event_outbox", ["status"], unique=False
    )
    op.create_table(
        "event_receipts",
        sa.Column("routing_key", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("correlation_id", sa.String(length=80), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_event_receipts_entity_id"),
        "event_receipts",
        ["entity_id"],
        unique=False,
    )
    op.create_table(
        "generated_audio",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=200), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("boundaries", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key"),
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("locator", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("received", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("analyzed", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ingestion_jobs_status"), "ingestion_jobs", ["status"], unique=False
    )
    op.create_table(
        "model_usage",
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=240), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("reference_id", sa.String(length=120), nullable=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_usage_reference_id"),
        "model_usage",
        ["reference_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_usage_stage"), "model_usage", ["stage"], unique=False
    )
    op.create_table(
        "processing_jobs",
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "entity_id"),
    )
    op.create_index(
        op.f("ix_processing_jobs_entity_id"),
        "processing_jobs",
        ["entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_processing_jobs_next_attempt"),
        "processing_jobs",
        ["next_attempt"],
        unique=False,
    )
    op.create_index(
        op.f("ix_processing_jobs_status"), "processing_jobs", ["status"], unique=False
    )
    op.create_table(
        "sources",
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "is_synthetic"),
    )
    op.create_table(
        "stories",
        sa.Column("title", sa.String(length=800), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("urgency", sa.Float(), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stories_category"), "stories", ["category"], unique=False)
    op.create_index(op.f("ix_stories_event_at"), "stories", ["event_at"], unique=False)
    op.create_index(
        op.f("ix_stories_importance"), "stories", ["importance"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=90), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "voice_profiles",
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "articles",
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=250), nullable=True),
        sa.Column("title", sa.String(length=800), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(length=240), nullable=True),
        sa.Column("language", sa.String(length=12), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("near_duplicate_of", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ingestion_jobs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["near_duplicate_of"],
            ["articles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash", "is_synthetic"),
    )
    op.create_index(op.f("ix_articles_job_id"), "articles", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_articles_language"), "articles", ["language"], unique=False
    )
    op.create_index(
        op.f("ix_articles_published_at"), "articles", ["published_at"], unique=False
    )
    op.create_index(
        "ix_articles_published_status",
        "articles",
        ["published_at", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_articles_source_id"), "articles", ["source_id"], unique=False
    )
    op.create_table(
        "briefing_schedules",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("time", sa.String(length=5), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_local_date", sa.Date(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_briefing_schedules_user_id"),
        "briefing_schedules",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "briefings",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("voice_profile_id", sa.String(length=80), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("schedule_key", sa.String(length=160), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("audio_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.String(length=400), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["audio_id"], ["generated_audio.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_key"),
    )
    op.create_index(op.f("ix_briefings_status"), "briefings", ["status"], unique=False)
    op.create_index(
        op.f("ix_briefings_user_id"), "briefings", ["user_id"], unique=False
    )
    op.create_table(
        "cost_events",
        sa.Column("usage_id", sa.String(length=36), nullable=False),
        sa.Column("measured_usd", sa.Float(), nullable=True),
        sa.Column("estimated_usd", sa.Float(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["usage_id"], ["model_usage.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usage_id"),
    )
    op.create_table(
        "facts",
        sa.Column("story_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_facts_status"), "facts", ["status"], unique=False)
    op.create_index(op.f("ix_facts_story_id"), "facts", ["story_id"], unique=False)
    op.create_table(
        "listening_history",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("story_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "story_id"),
    )
    op.create_index(
        op.f("ix_listening_history_user_id"),
        "listening_history",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "source_disagreements",
        sa.Column("story_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "fact_ids",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_disagreements_story_id"),
        "source_disagreements",
        ["story_id"],
        unique=False,
    )
    op.create_table(
        "story_topics",
        sa.Column("story_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_id", "name"),
    )
    op.create_index(
        op.f("ix_story_topics_name"), "story_topics", ["name"], unique=False
    )
    op.create_index(
        op.f("ix_story_topics_story_id"), "story_topics", ["story_id"], unique=False
    )
    op.create_table(
        "user_feedback",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("story_id", sa.String(length=36), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "story_id"),
    )
    op.create_index(
        op.f("ix_user_feedback_user_id"), "user_feedback", ["user_id"], unique=False
    )
    op.create_table(
        "user_interests",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "topic"),
    )
    op.create_index(
        op.f("ix_user_interests_user_id"), "user_interests", ["user_id"], unique=False
    )
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("voice_profile_id", sa.String(length=40), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("depth", sa.String(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["voice_profile_id"],
            ["voice_profiles.slug"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "user_sources",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_id"),
    )
    op.create_index(
        op.f("ix_user_sources_user_id"), "user_sources", ["user_id"], unique=False
    )
    op.create_table(
        "article_embeddings",
        sa.Column("article_id", sa.String(length=36), nullable=False),
        sa.Column("model", sa.String(length=180), nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.vector.VECTOR(dim=384).with_variant(
                sa.JSON(), "sqlite"
            ),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "ix_article_embeddings_cosine",
            "article_embeddings",
            ["embedding"],
            unique=False,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
    op.create_table(
        "briefing_items",
        sa.Column("briefing_id", sa.String(length=36), nullable=False),
        sa.Column("story_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=600), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["briefing_id"], ["briefings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("briefing_id", "position"),
    )
    op.create_index(
        op.f("ix_briefing_items_briefing_id"),
        "briefing_items",
        ["briefing_id"],
        unique=False,
    )
    op.create_table(
        "briefing_segments",
        sa.Column("briefing_id", sa.String(length=36), nullable=False),
        sa.Column("story_id", sa.String(length=36), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("claim_ids", sa.JSON(), nullable=False),
        sa.Column("source_article_ids", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("verification_status", sa.String(length=30), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["briefing_id"], ["briefings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("briefing_id", "position"),
    )
    op.create_index(
        op.f("ix_briefing_segments_briefing_id"),
        "briefing_segments",
        ["briefing_id"],
        unique=False,
    )
    op.create_table(
        "claim_evidence",
        sa.Column("fact_id", sa.String(length=36), nullable=False),
        sa.Column("article_id", sa.String(length=36), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fact_id"], ["facts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fact_id", "article_id", "start"),
    )
    op.create_index(
        op.f("ix_claim_evidence_article_id"),
        "claim_evidence",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_evidence_fact_id"), "claim_evidence", ["fact_id"], unique=False
    )
    op.create_table(
        "conversations",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("briefing_id", sa.String(length=36), nullable=True),
        sa.Column("story_id", sa.String(length=36), nullable=True),
        sa.Column("topic", sa.String(length=100), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["briefing_id"], ["briefings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False
    )
    op.create_table(
        "story_articles",
        sa.Column("story_id", sa.String(length=36), nullable=False),
        sa.Column("article_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id"),
    )
    op.create_index(
        op.f("ix_story_articles_story_id"), "story_articles", ["story_id"], unique=False
    )
    op.create_table(
        "conversation_messages",
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=12), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=35), nullable=True),
        sa.Column("story_id", sa.String(length=36), nullable=True),
        sa.Column("briefing_id", sa.String(length=36), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("action", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["briefing_id"], ["briefings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversation_messages_conversation_id"),
        "conversation_messages",
        ["conversation_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_conversation_messages_conversation_id"),
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_index(op.f("ix_story_articles_story_id"), table_name="story_articles")
    op.drop_table("story_articles")
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(op.f("ix_claim_evidence_fact_id"), table_name="claim_evidence")
    op.drop_index(op.f("ix_claim_evidence_article_id"), table_name="claim_evidence")
    op.drop_table("claim_evidence")
    op.drop_index(
        op.f("ix_briefing_segments_briefing_id"), table_name="briefing_segments"
    )
    op.drop_table("briefing_segments")
    op.drop_index(op.f("ix_briefing_items_briefing_id"), table_name="briefing_items")
    op.drop_table("briefing_items")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index(
            "ix_article_embeddings_cosine",
            table_name="article_embeddings",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
    op.drop_table("article_embeddings")
    op.drop_index(op.f("ix_user_sources_user_id"), table_name="user_sources")
    op.drop_table("user_sources")
    op.drop_table("user_preferences")
    op.drop_index(op.f("ix_user_interests_user_id"), table_name="user_interests")
    op.drop_table("user_interests")
    op.drop_index(op.f("ix_user_feedback_user_id"), table_name="user_feedback")
    op.drop_table("user_feedback")
    op.drop_index(op.f("ix_story_topics_story_id"), table_name="story_topics")
    op.drop_index(op.f("ix_story_topics_name"), table_name="story_topics")
    op.drop_table("story_topics")
    op.drop_index(
        op.f("ix_source_disagreements_story_id"), table_name="source_disagreements"
    )
    op.drop_table("source_disagreements")
    op.drop_index(op.f("ix_listening_history_user_id"), table_name="listening_history")
    op.drop_table("listening_history")
    op.drop_index(op.f("ix_facts_story_id"), table_name="facts")
    op.drop_index(op.f("ix_facts_status"), table_name="facts")
    op.drop_table("facts")
    op.drop_table("cost_events")
    op.drop_index(op.f("ix_briefings_user_id"), table_name="briefings")
    op.drop_index(op.f("ix_briefings_status"), table_name="briefings")
    op.drop_table("briefings")
    op.drop_index(
        op.f("ix_briefing_schedules_user_id"), table_name="briefing_schedules"
    )
    op.drop_table("briefing_schedules")
    op.drop_index(op.f("ix_articles_source_id"), table_name="articles")
    op.drop_index("ix_articles_published_status", table_name="articles")
    op.drop_index(op.f("ix_articles_published_at"), table_name="articles")
    op.drop_index(op.f("ix_articles_language"), table_name="articles")
    op.drop_index(op.f("ix_articles_job_id"), table_name="articles")
    op.drop_table("articles")
    op.drop_table("voice_profiles")
    op.drop_table("users")
    op.drop_index(op.f("ix_stories_importance"), table_name="stories")
    op.drop_index(op.f("ix_stories_event_at"), table_name="stories")
    op.drop_index(op.f("ix_stories_category"), table_name="stories")
    op.drop_table("stories")
    op.drop_table("sources")
    op.drop_index(op.f("ix_processing_jobs_status"), table_name="processing_jobs")
    op.drop_index(op.f("ix_processing_jobs_next_attempt"), table_name="processing_jobs")
    op.drop_index(op.f("ix_processing_jobs_entity_id"), table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_index(op.f("ix_model_usage_stage"), table_name="model_usage")
    op.drop_index(op.f("ix_model_usage_reference_id"), table_name="model_usage")
    op.drop_table("model_usage")
    op.drop_index(op.f("ix_ingestion_jobs_status"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_table("generated_audio")
    op.drop_index(op.f("ix_event_receipts_entity_id"), table_name="event_receipts")
    op.drop_table("event_receipts")
    op.drop_index(op.f("ix_event_outbox_status"), table_name="event_outbox")
    op.drop_table("event_outbox")
