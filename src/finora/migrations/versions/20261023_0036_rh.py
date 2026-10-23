"""RH: perfil do funcionário e histórico (salário, férias, 13º, benefícios) (módulo "hr")

Revisão: 0036
Anterior: 0035
Criada em: 2026-10-23 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'employee_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('job_title', sa.String(length=80), nullable=True),
        sa.Column('staff_category', sa.String(length=15), nullable=False),
        sa.Column('employment_type', sa.String(length=30), nullable=True),
        sa.Column('union_name', sa.String(length=120), nullable=True),
        sa.Column('workplace', sa.String(length=120), nullable=True),
        sa.Column('inss_rate', sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column('monthly_hours', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('initial_salary', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('admission_date', sa.Date(), nullable=True),
        sa.Column('termination_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contact_id'),
    )
    op.create_index('ix_employee_profiles_entity_id', 'employee_profiles', ['entity_id'])
    op.create_table(
        'employee_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('day', sa.Date(), nullable=True),
        sa.Column('end_day', sa.Date(), nullable=True),
        sa.Column('period', sa.String(length=30), nullable=True),
        sa.Column('name', sa.String(length=80), nullable=True),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('net_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_employee_records_entity_id', 'employee_records', ['entity_id'])
    op.create_index('ix_employee_records_contact_id', 'employee_records', ['contact_id'])


def downgrade() -> None:
    op.drop_index('ix_employee_records_contact_id', table_name='employee_records')
    op.drop_index('ix_employee_records_entity_id', table_name='employee_records')
    op.drop_table('employee_records')
    op.drop_index('ix_employee_profiles_entity_id', table_name='employee_profiles')
    op.drop_table('employee_profiles')
