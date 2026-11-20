"""Store one pending voice sample per listener."""

from alembic import op
import sqlalchemy as sa

revision = "0004_custom_voice_sample"
down_revision = "0003_custom_voice"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("custom_voice_sample", sa.LargeBinary()))


def downgrade():
    op.drop_column("users", "custom_voice_sample")
