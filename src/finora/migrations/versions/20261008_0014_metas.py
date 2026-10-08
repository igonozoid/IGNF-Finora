"""Metas e objetivos

Revisão: 0014
Anterior: 0013
Criada em: 2026-10-08 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'goals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('target', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('saved', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('goals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_goals_entity_id'), ['entity_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('goals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_goals_entity_id'))
    op.drop_table('goals')
