"""Entidade: bairro, complemento, país e "usa centro de custo"

Revisão: 0026
Anterior: 0025
Criada em: 2026-10-16 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('entities', schema=None) as batch_op:
        batch_op.add_column(sa.Column('address2', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('district', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('uses_cost_centers', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table('entities', schema=None) as batch_op:
        batch_op.drop_column('uses_cost_centers')
        batch_op.drop_column('country')
        batch_op.drop_column('district')
        batch_op.drop_column('address2')
