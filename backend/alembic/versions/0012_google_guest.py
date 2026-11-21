"""Guest accounts and stable Google identities."""
from alembic import op
import sqlalchemy as sa
revision = '0012_google_guest'
down_revision = '0011_notifications_voices'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('is_guest', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('google_sub', sa.String(255), nullable=True))
    op.create_index('uq_users_google_sub', 'users', ['google_sub'], unique=True)


def downgrade():
    op.drop_index('uq_users_google_sub', table_name='users')
    op.drop_column('users', 'google_sub')
    op.drop_column('users', 'is_guest')
