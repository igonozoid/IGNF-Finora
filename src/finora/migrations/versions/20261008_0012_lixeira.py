"""Lixeira

Revisão: 0012
Anterior: 0011
Criada em: 2026-10-08 18:10:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('deleted_by', sa.String(length=80), nullable=True))
        batch_op.create_index(batch_op.f('ix_entries_deleted_at'), ['deleted_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('entries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_entries_deleted_at'))
        batch_op.drop_column('deleted_by')
        batch_op.drop_column('deleted_at')
