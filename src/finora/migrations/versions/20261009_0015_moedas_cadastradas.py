"""Moedas cadastradas pela pessoa

Revisão: 0015
Anterior: 0014
Criada em: 2026-10-09 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'currencies',
        sa.Column('code', sa.String(length=3), nullable=False),
        sa.Column('symbol', sa.String(length=6), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.PrimaryKeyConstraint('code'),
    )


def downgrade() -> None:
    op.drop_table('currencies')
