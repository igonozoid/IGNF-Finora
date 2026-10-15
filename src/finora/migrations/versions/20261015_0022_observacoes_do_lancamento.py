"""Observações do lançamento

Revisão: 0022
Anterior: 0021
Criada em: 2026-10-15 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('entries', schema=None) as batch_op:
        batch_op.drop_column('notes')
