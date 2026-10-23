"""Contato: aniversário e data importante (aparecem nos lembretes)

Revisão: 0033
Anterior: 0032
Criada em: 2026-10-23 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('birthday', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('important_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('important_label', sa.String(length=60), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        for col in ('important_label', 'important_date', 'birthday'):
            batch_op.drop_column(col)
