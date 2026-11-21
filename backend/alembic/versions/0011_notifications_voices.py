"""Private voice collections and scheduled edition notifications."""
from alembic import op
import sqlalchemy as sa
revision = "0011_notifications_voices"
down_revision = "0010_custom_topics"
branch_labels = None
depends_on = None

def base():
    return [sa.Column("id", sa.String(36), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)]

def upgrade():
    op.create_table("listener_voices", *base(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("preset_slug", sa.String(80)), sa.Column("provider_voice_id", sa.String(128)),
        sa.Column("name", sa.String(100), nullable=False), sa.Column("persona", sa.String(600), nullable=False),
        sa.Column("favorite", sa.Boolean(), nullable=False), sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "preset_slug"), sa.UniqueConstraint("user_id", "provider_voice_id"))
    op.create_index("ix_listener_voices_user_id", "listener_voices", ["user_id"])
    op.create_table("push_subscriptions", *base(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("keys", sa.JSON(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False))
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_table("listener_notifications", *base(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("briefing_id", sa.String(36), sa.ForeignKey("briefings.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("sent_to", sa.JSON(), nullable=False))
    op.create_index("ix_listener_notifications_user_id", "listener_notifications", ["user_id"])
    # Preserve every already saved private voice, including its owner and name.
    op.execute("INSERT INTO listener_voices (id,created_at,user_id,provider_voice_id,name,persona,favorite,hidden) SELECT id,created_at,id,custom_voice_id,custom_voice_name,custom_voice_persona,true,false FROM users WHERE custom_voice_id IS NOT NULL")

def downgrade():
    op.drop_table("listener_notifications")
    op.drop_table("push_subscriptions")
    op.drop_table("listener_voices")
