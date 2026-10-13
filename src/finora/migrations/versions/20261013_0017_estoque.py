"""Produtos e estoque

Revisão: 0017
Anterior: 0016
Criada em: 2026-10-13 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('unit', sa.String(length=10), nullable=False),
        sa.Column('sale_price', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('min_stock', sa.Numeric(precision=15, scale=3), nullable=True),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_items_entity_id'), ['entity_id'], unique=False)
    op.create_table(
        'stock_locations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('stock_locations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stock_locations_entity_id'), ['entity_id'], unique=False)
    op.create_table(
        'stock_moves',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=15, scale=3), nullable=False),
        sa.Column('unit_cost', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('entry_id', sa.Integer(), nullable=True),
        sa.Column('transfer_id', sa.String(length=32), nullable=True),
        sa.Column('document_no', sa.String(length=40), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['entry_id'], ['entries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['item_id'], ['items.id']),
        sa.ForeignKeyConstraint(['location_id'], ['stock_locations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stock_moves_entity_id'), ['entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_moves_item_id'), ['item_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_moves_transfer_id'), ['transfer_id'], unique=False)


def downgrade() -> None:
    op.drop_table('stock_moves')
    op.drop_table('stock_locations')
    op.drop_table('items')
