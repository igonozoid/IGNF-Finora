"""Vínculo da importação (reimportar sem duplicar)

Revisão: 0029
Anterior: 0028
Criada em: 2026-10-16 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'import_map',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('source_id', sa.String(length=160), nullable=False),
        sa.Column('target', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'kind', 'source_id', name='uq_import_map'),
    )


def downgrade() -> None:
    op.drop_table('import_map')
