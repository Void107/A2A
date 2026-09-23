"""Version-scoped consumer evidence; does not alter immutable contract documents."""
from alembic import op
import sqlalchemy as sa
revision = '20260914_publication'
down_revision = '20260914_failures'
branch_labels = depends_on = None


def upgrade():
    op.create_table('publication_checks',
        sa.Column('contract_id', sa.String(64), primary_key=True),
        sa.Column('contract_version', sa.String(50), primary_key=True),
        sa.Column('bundle', sa.JSON(), nullable=False),
        sa.Column('report', sa.JSON(), nullable=False),
        sa.Column('acknowledged_digest', sa.String(64), nullable=True))


def downgrade():
    raise RuntimeError('Publication history downgrade disabled')
