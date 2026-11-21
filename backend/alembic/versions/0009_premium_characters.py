"""Gate premium character selection without changing archived audio."""

from alembic import op
import sqlalchemy as sa

revision = "0009_premium_characters"
down_revision = "0008_retire_street_signal"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "is_premium", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.execute(
        sa.text(
            "UPDATE user_preferences SET voice_profile_id='professional' WHERE voice_profile_id='gangsta'"
        )
    )


def downgrade():
    op.drop_column("users", "is_premium")
