"""Retire Street Signal while keeping historical episodes playable."""

from alembic import op
import sqlalchemy as sa

revision = "0008_retire_street_signal"
down_revision = "0007_trump_voice"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            "UPDATE user_preferences SET voice_profile_id='professional' WHERE voice_profile_id='casual'"
        )
    )


def downgrade():
    pass
