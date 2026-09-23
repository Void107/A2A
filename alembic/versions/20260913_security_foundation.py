"""Trusted identity and independent grants. Legacy identities require reapproval."""
from alembic import op
import sqlalchemy as sa

revision = '20260913_security'
down_revision = '4e303a674a86'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('agents', sa.Column('roles', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('agents', sa.Column('authorization_revision', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('agents', sa.Column('credential_revision', sa.Integer(), nullable=False, server_default='1'))
    op.alter_column('agents', 'scopes', server_default='[]')
    # Existing self-registered organization claims cannot become trusted identities.
    op.execute("UPDATE agents SET is_active=false, scopes='[]', domain=NULL")
    op.create_table('access_grants',
        sa.Column('grant_id', sa.String(64), primary_key=True),
        sa.Column('agent_id', sa.String(255), nullable=False),
        sa.Column('contract_id', sa.String(64), nullable=False),
        sa.Column('view_id', sa.String(64), nullable=False),
        sa.Column('allowed_meeting_ids', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False))
    op.create_index('ix_access_grants_agent_id', 'access_grants', ['agent_id'])
    op.create_table('public_resources',
        sa.Column('contract_id', sa.String(64), primary_key=True),
        sa.Column('contract_version', sa.String(50), primary_key=True),
        sa.Column('owner_agent_id', sa.String(255), nullable=False),
        sa.Column('public', sa.Boolean(), nullable=False))


def downgrade():
    raise RuntimeError('Security downgrade disabled: never reactivate legacy identities; use forward migration')
