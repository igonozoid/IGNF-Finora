"""Categoria e centro de custo: marca "a revisar" (criados no lançamento ou na importação)

Revisão: 0034
Anterior: 0033
Criada em: 2026-10-23 19:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('categories', 'cost_centers'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('needs_review', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table in ('cost_centers', 'categories'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('needs_review')
