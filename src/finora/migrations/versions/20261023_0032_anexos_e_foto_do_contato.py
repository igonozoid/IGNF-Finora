"""Anexos e foto do contato

Revisão: 0032
Anterior: 0031
Criada em: 2026-10-23 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo', sa.LargeBinary(length=500000), nullable=True))
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.alter_column('entry_id', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column('contact_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_attachments_contact_id'), ['contact_id'], unique=False)
        batch_op.create_foreign_key('fk_attachments_contact_id', 'contacts', ['contact_id'], ['id'],
                                    ondelete='CASCADE')


def downgrade() -> None:
    op.execute("DELETE FROM attachments WHERE entry_id IS NULL")
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_attachments_contact_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_attachments_contact_id'))
        batch_op.drop_column('contact_id')
        batch_op.alter_column('entry_id', existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.drop_column('photo')
