"""Agricultura (propriedades, áreas e atividades)

Revisão: 0020
Anterior: 0019
Criada em: 2026-10-13 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'farms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('city', sa.String(length=80), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('farms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_farms_entity_id'), ['entity_id'], unique=False)
    op.create_table(
        'farm_areas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('farm_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('crop', sa.String(length=80), nullable=True),
        sa.Column('hectares', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('units', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('farm_areas', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_farm_areas_entity_id'), ['entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_farm_areas_farm_id'), ['farm_id'], unique=False)
    op.create_table(
        'farm_activities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('area_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('other_cost', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('inputs_cost', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('harvest_cost', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['area_id'], ['farm_areas.id']),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['location_id'], ['stock_locations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('farm_activities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_farm_activities_area_id'), ['area_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_farm_activities_entity_id'), ['entity_id'], unique=False)
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.add_column(sa.Column('activity_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_stock_moves_activity_id'), ['activity_id'], unique=False)
        batch_op.create_foreign_key('fk_stock_moves_activity_id', 'farm_activities', ['activity_id'], ['id'],
                                    ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('stock_moves', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stock_moves_activity_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stock_moves_activity_id'))
        batch_op.drop_column('activity_id')
    op.drop_table('farm_activities')
    op.drop_table('farm_areas')
    op.drop_table('farms')
