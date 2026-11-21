"""Keep the topic library independently from the selected interests."""

from collections import defaultdict
from alembic import op
import sqlalchemy as sa

revision = "0010_custom_topics"
down_revision = "0009_premium_characters"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_preferences",
        sa.Column(
            "custom_topics", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )
    bind = op.get_bind()
    topics = defaultdict(list)
    known = set(bind.execute(sa.text("SELECT name FROM story_topics")).scalars())
    known.update(bind.execute(sa.text("SELECT category FROM stories")).scalars())
    for uid, topic in bind.execute(
        sa.text("SELECT user_id, topic FROM user_interests")
    ):
        if topic not in known:
            topics[uid].append(topic)
    table = sa.table(
        "user_preferences",
        sa.column("user_id", sa.String()),
        sa.column("custom_topics", sa.JSON()),
    )
    for uid, values in topics.items():
        bind.execute(
            table.update().where(table.c.user_id == uid).values(custom_topics=values)
        )


def downgrade():
    op.drop_column("user_preferences", "custom_topics")
