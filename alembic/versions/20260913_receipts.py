"""Transactional receipt, durable outbox and idempotent audit index."""
from alembic import op
import sqlalchemy as sa

revision = '20260913_receipts'
down_revision = '20260913_security'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('delivery_receipts',
        sa.Column('request_id', sa.String(64), primary_key=True),
        sa.Column('source_agent', sa.String(255), nullable=False),
        sa.Column('target_agent', sa.String(255), nullable=False),
        sa.Column('contract_id', sa.String(64), nullable=False),
        sa.Column('contract_version', sa.String(50), nullable=False),
        sa.Column('contract_digest', sa.String(64), nullable=False),
        sa.Column('view_id', sa.String(64), nullable=False),
        sa.Column('meeting_id', sa.String(64), nullable=False),
        sa.Column('policy_revision', sa.String(64), nullable=False),
        sa.Column('profile_revision', sa.String(64), nullable=False),
        sa.Column('completed_processors', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_delivery_receipts_source_agent', 'delivery_receipts', ['source_agent'])
    op.create_table('outbox_events',
        sa.Column('event_id', sa.String(64), primary_key=True),
        sa.Column('receipt_id', sa.String(64), nullable=False, unique=True),
        sa.Column('processed', sa.Boolean(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt', sa.DateTime(), nullable=False))
    op.create_table('delivery_audit',
        sa.Column('event_id', sa.String(64), primary_key=True),
        sa.Column('receipt_id', sa.String(64), nullable=False, unique=True),
        sa.Column('indexed_at', sa.DateTime(), nullable=False))


def downgrade():
    raise RuntimeError('Receipt history must not be destroyed by downgrade')
