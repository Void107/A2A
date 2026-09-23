"""Safe failure records and PG-backed replay protection."""
from alembic import op
import sqlalchemy as sa
revision = '20260914_failures'
down_revision = '20260914_contracts'
branch_labels = depends_on = None


def upgrade():
    op.create_table('failure_records', sa.Column('request_id', sa.String(64), primary_key=True),
        sa.Column('source_agent', sa.String(255), nullable=False), sa.Column('code', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('upstream_nonces', sa.Column('nonce', sa.String(256), primary_key=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False))


def downgrade():
    raise RuntimeError('Security history downgrade disabled')
