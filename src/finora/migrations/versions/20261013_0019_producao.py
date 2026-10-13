"""Produção (lotes)

Revisão: 0019
Anterior: 0018
Criada em: 2026-10-13 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'productions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('extra_cost', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['location_id'], ['stock_locations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('productions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_productions_entity_id'), ['entity_id'], unique=False)
    op.create_table(
        'production_lines',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('production_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=3), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=15, scale=3), nullable=False),
        sa.Column('share', sa.Numeric(precision=7, scale=3), nullable=True),
        sa.Column('unit_cost', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['items.id']),
        sa.ForeignKeyConstraint(['production_id'], ['productions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('production_lines', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_production_lines_production_id'), ['production_id'], unique=False)
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.add_column(sa.Column('production_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_stock_moves_production_id'), ['production_id'], unique=False)
        batch_op.create_foreign_key('fk_stock_moves_production_id', 'productions', ['production_id'], ['id'],
                                    ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stock_moves_production_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stock_moves_production_id'))
        batch_op.drop_column('production_id')
    op.drop_table('production_lines')
    op.drop_table('productions')
