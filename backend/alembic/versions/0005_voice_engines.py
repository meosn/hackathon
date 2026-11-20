"""Persist each listener's voice engine and the shared character voice bindings."""
from alembic import op
import sqlalchemy as sa

revision = "0005_voice_engines"
down_revision = "0004_custom_voice_sample"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("custom_voice_name", sa.String(80), nullable=False, server_default="Custom"))
    op.add_column("users", sa.Column("custom_voice_persona", sa.String(600), nullable=False, server_default="Natural, conversational delivery."))
    op.add_column("user_preferences", sa.Column("voice_engine", sa.String(24), nullable=False, server_default="openai"))
    op.add_column("voice_profiles", sa.Column("elevenlabs_voice_id", sa.String(128)))
    op.add_column("voice_profiles", sa.Column("openai_voice", sa.String(24), nullable=False, server_default="marin"))
    op.add_column("voice_profiles", sa.Column("persona", sa.String(), nullable=False, server_default=""))


def downgrade():
    op.drop_column("users", "custom_voice_persona")
    op.drop_column("users", "custom_voice_name")
    for name in ("persona", "openai_voice", "elevenlabs_voice_id"):
        op.drop_column("voice_profiles", name)
    op.drop_column("user_preferences", "voice_engine")
