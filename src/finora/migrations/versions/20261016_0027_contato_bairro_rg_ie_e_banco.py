"""Contato: bairro, RG/IE, pessoa de contato e dados bancários em campos separados

Revisão: 0027
Anterior: 0026
Criada em: 2026-10-16 13:00:00

O texto livre "banco · agência · conta" (bank_info) é repartido nos campos novos e a coluna sai.
"""
from alembic import op
import sqlalchemy as sa


revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None

NEW = [('district', 80), ('document2', 30), ('contact_person', 80), ('bank_name', 60), ('bank_branch', 20),
       ('bank_account', 30), ('bank_holder', 120)]


def split_bank_info(text: str | None) -> tuple[str | None, str | None, str | None]:
    """'Itaú · 0412 · 55210-3' -> ('Itaú', '0412', '55210-3'). Fora desse formato, tudo vai para o banco."""
    text = (text or "").strip()
    if not text:
        return None, None, None
    parts = [p.strip() for p in text.replace("|", "·").split("·")]
    if len(parts) == 3 and all(parts):
        return parts[0][:60], parts[1][:20], parts[2][:30]
    return text[:60], None, None


def upgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        for name, size in NEW:
            batch_op.add_column(sa.Column(name, sa.String(length=size), nullable=True))
    bind = op.get_bind()
    contacts = sa.table('contacts', sa.column('id', sa.Integer), sa.column('bank_info', sa.String),
                        sa.column('bank_name', sa.String), sa.column('bank_branch', sa.String),
                        sa.column('bank_account', sa.String))
    rows = bind.execute(sa.select(contacts.c.id, contacts.c.bank_info).where(contacts.c.bank_info.is_not(None)))
    for cid, info in list(rows):
        name, branch, account = split_bank_info(info)
        bind.execute(contacts.update().where(contacts.c.id == cid)
                     .values(bank_name=name, bank_branch=branch, bank_account=account))
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.drop_column('bank_info')


def downgrade() -> None:
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bank_info', sa.String(length=120), nullable=True))
    bind = op.get_bind()
    contacts = sa.table('contacts', sa.column('id', sa.Integer), sa.column('bank_info', sa.String),
                        sa.column('bank_name', sa.String), sa.column('bank_branch', sa.String),
                        sa.column('bank_account', sa.String))
    for cid, name, branch, account in list(bind.execute(sa.select(
            contacts.c.id, contacts.c.bank_name, contacts.c.bank_branch, contacts.c.bank_account))):
        info = " · ".join(x for x in (name, branch, account) if x)
        if info:
            bind.execute(contacts.update().where(contacts.c.id == cid).values(bank_info=info[:120]))
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        for name, _size in reversed(NEW):
            batch_op.drop_column(name)
