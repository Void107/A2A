"""Add optional bounded failure metadata; historical rows remain unknown."""
from alembic import op
import sqlalchemy as sa
revision = '20260922_diagnostics'
down_revision = '20260914_publication'
branch_labels = depends_on = None


def upgrade():
    op.add_column('failure_records', sa.Column('diagnostics', sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError('Failure diagnostic history downgrade disabled')
