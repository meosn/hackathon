"""Make ElevenLabs the initial voice provider for all listeners."""
from alembic import op
import sqlalchemy as sa

revision = "0013_default_elevenlabs"
down_revision = "0012_google_guest"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("user_preferences", "voice_engine", existing_type=sa.String(24), server_default="elevenlabs")
    op.execute("UPDATE user_preferences SET voice_engine = 'elevenlabs' WHERE voice_engine = 'openai'")


def downgrade():
    op.alter_column("user_preferences", "voice_engine", existing_type=sa.String(24), server_default="openai")
