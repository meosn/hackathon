"""Listener choice of evidence-only or configured model intent recognition."""

from alembic import op
import sqlalchemy as sa

revision = "0002_discussion_model"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_preferences",
        sa.Column(
            "discussion_model",
            sa.String(24),
            nullable=False,
            server_default="configured",
        ),
    )


def downgrade():
    op.drop_column("user_preferences", "discussion_model")
