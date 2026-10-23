"""Agenda: tarefas (módulo "agenda")

Revisão: 0035
Anterior: 0034
Criada em: 2026-10-23 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('done_at', sa.DateTime(), nullable=True),
        sa.Column('recurrence', sa.String(length=12), nullable=False),
        sa.Column('recurrence_day', sa.Integer(), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('entry_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entry_id'], ['entries.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tasks_entity_id', 'tasks', ['entity_id'])
    op.create_index('ix_tasks_due_date', 'tasks', ['due_date'])


def downgrade() -> None:
    op.drop_index('ix_tasks_due_date', table_name='tasks')
    op.drop_index('ix_tasks_entity_id', table_name='tasks')
    op.drop_table('tasks')
