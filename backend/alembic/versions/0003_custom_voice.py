"""Store the listener's private live voice selection."""

from alembic import op
import sqlalchemy as sa

revision = "0003_custom_voice"
down_revision = "0002_discussion_model"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("custom_voice_id", sa.String(128)))
    op.add_column(
        "users",
        sa.Column(
            "custom_voice_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column("users", "custom_voice_active")
    op.drop_column("users", "custom_voice_id")
