"""Valor previsto quando o pagamento sai diferente (juros, multa, desconto)

Revisão: 0023
Anterior: 0022
Criada em: 2026-10-16 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('original_amount', sa.Numeric(precision=15, scale=2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('entries', schema=None) as batch_op:
        batch_op.drop_column('original_amount')
