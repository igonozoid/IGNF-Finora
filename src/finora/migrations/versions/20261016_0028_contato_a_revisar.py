"""Contato: marca "a revisar" (criado sozinho pela importação)

Revisão: 0028
Anterior: 0027
Criada em: 2026-10-16 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('needs_review', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.drop_column('needs_review')
