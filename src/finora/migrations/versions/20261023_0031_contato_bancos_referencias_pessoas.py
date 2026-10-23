"""Contato: outras contas bancárias, referências e pessoas de contato

Revisão: 0031
Anterior: 0030
Criada em: 2026-10-23 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def _contact_fk():
    return [sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('contact_id', sa.Integer(), nullable=False)]


def upgrade() -> None:
    op.create_table(
        'contact_banks', *_contact_fk(),
        sa.Column('bank_name', sa.String(length=60), nullable=False),
        sa.Column('bank_branch', sa.String(length=20), nullable=True),
        sa.Column('bank_account', sa.String(length=30), nullable=True),
        sa.Column('holder', sa.String(length=120), nullable=True),
        sa.Column('pix_key', sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'contact_references', *_contact_fk(),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('notes', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'contact_people', *_contact_fk(),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('job', sa.String(length=60), nullable=True),
        sa.Column('extension', sa.String(length=10), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    for table in ('contact_banks', 'contact_references', 'contact_people'):
        op.create_index(f'ix_{table}_contact_id', table, ['contact_id'])


def downgrade() -> None:
    for table in ('contact_people', 'contact_references', 'contact_banks'):
        op.drop_index(f'ix_{table}_contact_id', table_name=table)
        op.drop_table(table)
