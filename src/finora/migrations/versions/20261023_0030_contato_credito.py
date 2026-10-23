"""Contato: crédito (limite, consulta, pendência, nome da mãe, classificação, frequência de compra)

Revisão: 0030
Anterior: 0029
Criada em: 2026-10-23 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('credit_limit', sa.Numeric(precision=15, scale=2), nullable=True))
        batch_op.add_column(sa.Column('credit_checked_on', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('credit_pending', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('credit_pending_where', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('mother_name', sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column('rating', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('purchase_frequency', sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        for col in ('purchase_frequency', 'rating', 'mother_name', 'credit_pending_where', 'credit_pending',
                    'credit_checked_on', 'credit_limit'):
            batch_op.drop_column(col)
