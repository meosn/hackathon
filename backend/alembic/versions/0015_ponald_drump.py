"""Rename the supplied character in existing voice catalogs."""
from alembic import op
import sqlalchemy as sa

revision = "0015_ponald_drump"
down_revision = "0014_granny_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "UPDATE voice_profiles SET name=:name WHERE slug='energetic'"
    ).bindparams(name="Ponald Drump"))


def downgrade():
    op.execute(sa.text(
        "UPDATE voice_profiles SET name=:name WHERE slug='energetic'"
    ).bindparams(name="Donald Trump"))
