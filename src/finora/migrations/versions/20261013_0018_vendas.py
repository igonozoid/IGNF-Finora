"""Vendas (pedidos)

Revisão: 0018
Anterior: 0017
Criada em: 2026-10-13 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sales',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('discount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('freight', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('payment', sa.String(length=20), nullable=True),
        sa.Column('installments', sa.Integer(), nullable=False),
        sa.Column('first_due', sa.Date(), nullable=True),
        sa.Column('paid_now', sa.Boolean(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('series_id', sa.String(length=32), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['location_id'], ['stock_locations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sales_entity_id'), ['entity_id'], unique=False)
    op.create_table(
        'sale_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sale_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=15, scale=3), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('unit_cost', sa.Numeric(precision=15, scale=4), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['items.id']),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('sale_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sale_items_sale_id'), ['sale_id'], unique=False)
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sale_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_stock_moves_sale_id'), ['sale_id'], unique=False)
        batch_op.create_foreign_key('fk_stock_moves_sale_id', 'sales', ['sale_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stock_moves_sale_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stock_moves_sale_id'))
        batch_op.drop_column('sale_id')
    op.drop_table('sale_items')
    op.drop_table('sales')
