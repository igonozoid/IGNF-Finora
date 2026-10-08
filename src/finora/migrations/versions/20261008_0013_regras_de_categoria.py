"""Regras automáticas de categoria

Revisão: 0013
Anterior: 0012
Criada em: 2026-10-08 19:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'category_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(length=80), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('cost_center_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['cost_center_id'], ['cost_centers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_category_rules_entity_id'), ['entity_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('category_rules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_category_rules_entity_id'))
    op.drop_table('category_rules')
