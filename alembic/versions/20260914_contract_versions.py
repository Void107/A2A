"""Immutable contract version storage."""
from alembic import op
import sqlalchemy as sa
revision = '20260914_contracts'
down_revision = '20260913_receipts'
branch_labels = depends_on = None


def upgrade():
    op.create_table('contract_resources', sa.Column('contract_id', sa.String(64), primary_key=True),
                    sa.Column('owner_agent_id', sa.String(255), nullable=False),
                    sa.Column('provider_agent_id', sa.String(255), nullable=False))
    op.create_table('contract_versions',
        sa.Column('contract_id', sa.String(64), primary_key=True),
        sa.Column('contract_version', sa.String(50), primary_key=True),
        sa.Column('owner_agent_id', sa.String(255), nullable=False),
        sa.Column('provider_agent_id', sa.String(255), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False))
    op.execute('''CREATE FUNCTION reject_contract_document_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.document::jsonb IS DISTINCT FROM OLD.document::jsonb OR NEW.digest <> OLD.digest
         OR NEW.owner_agent_id <> OLD.owner_agent_id OR NEW.provider_agent_id <> OLD.provider_agent_id
         OR NEW.contract_id <> OLD.contract_id OR NEW.contract_version <> OLD.contract_version THEN
        RAISE EXCEPTION 'immutable contract version';
      END IF;
      IF OLD.state = 'retired' AND NEW.state <> 'retired' THEN
        RAISE EXCEPTION 'retired contract cannot reactivate';
      END IF;
      RETURN NEW;
    END $$''')
    op.execute('CREATE TRIGGER immutable_contract_version BEFORE UPDATE ON contract_versions FOR EACH ROW EXECUTE FUNCTION reject_contract_document_update()')
    op.create_index('one_default_contract_version', 'contract_versions', ['contract_id'], unique=True,
                    postgresql_where=sa.text('is_default = true'))


def downgrade():
    raise RuntimeError('Contract history downgrade disabled')
