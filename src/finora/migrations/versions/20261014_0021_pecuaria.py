"""Pecuária por lote

Revisão: 0021
Anterior: 0020
Criada em: 2026-10-14 00:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'herd_lots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('species', sa.String(length=12), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=True),
        sa.Column('area_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['area_id'], ['farm_areas.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('herd_lots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_herd_lots_entity_id'), ['entity_id'], unique=False)
    op.create_table(
        'herd_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('lot_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('heads', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('value', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('other_cost', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('inputs_cost', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('area_id', sa.Integer(), nullable=True),
        sa.Column('other_lot_id', sa.Integer(), nullable=True),
        sa.Column('transfer_id', sa.String(length=32), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('entry_id', sa.Integer(), nullable=True),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['area_id'], ['farm_areas.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['entry_id'], ['entries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['location_id'], ['stock_locations.id']),
        sa.ForeignKeyConstraint(['lot_id'], ['herd_lots.id']),
        sa.ForeignKeyConstraint(['other_lot_id'], ['herd_lots.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('herd_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_herd_events_entity_id'), ['entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_herd_events_lot_id'), ['lot_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_herd_events_transfer_id'), ['transfer_id'], unique=False)
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.add_column(sa.Column('herd_event_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_stock_moves_herd_event_id'), ['herd_event_id'], unique=False)
        batch_op.create_foreign_key('fk_stock_moves_herd_event_id', 'herd_events', ['herd_event_id'], ['id'],
                                    ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stock_moves_herd_event_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stock_moves_herd_event_id'))
        batch_op.drop_column('herd_event_id')
    op.drop_table('herd_events')
    op.drop_table('herd_lots')
