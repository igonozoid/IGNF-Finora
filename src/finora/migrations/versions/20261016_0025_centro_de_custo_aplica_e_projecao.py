"""Centro de custo: aplica a despesas/receitas e projeção de receita

Revisão: 0025
Anterior: 0024
Criada em: 2026-10-16 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # os que já existem continuam valendo para os dois tipos
    with op.batch_alter_table('cost_centers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('applies_expense', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('applies_income', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('projection', sa.Numeric(precision=15, scale=2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('cost_centers', schema=None) as batch_op:
        batch_op.drop_column('projection')
        batch_op.drop_column('applies_income')
        batch_op.drop_column('applies_expense')
