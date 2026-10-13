"""Módulos por entidade e modelo da DRE (pessoal ou empresa)

Revisão: 0016
Anterior: 0015
Criada em: 2026-10-13 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('entities', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dre_model', sa.String(length=10), nullable=False,
                                      server_default='personal'))
    op.create_table(
        'entity_modules',
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('module', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('entity_id', 'module'),
    )


def downgrade() -> None:
    op.drop_table('entity_modules')
    with op.batch_alter_table('entities', schema=None) as batch_op:
        batch_op.drop_column('dre_model')
