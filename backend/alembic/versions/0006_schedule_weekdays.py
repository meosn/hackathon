"""Add weekday selection while retaining existing daily delivery times."""
from alembic import op
import sqlalchemy as sa

revision = "0006_schedule_weekdays"
down_revision = "0005_voice_engines"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("briefing_schedules", sa.Column("days_of_week", sa.JSON(), nullable=False, server_default="[0,1,2,3,4,5,6]"))


def downgrade():
    op.drop_column("briefing_schedules", "days_of_week")
