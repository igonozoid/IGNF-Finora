"""Lixeira: lançamento excluído não sai do banco. Ganha a data e quem excluiu e some de todas as telas, saldos
e relatórios; dá para restaurar quando quiser.

O sumiço vale para qualquer consulta do app (gancho do_orm_execute), não só para as telas: um relatório novo não
precisa lembrar de filtrar. Para enxergar a lixeira, a consulta pede `execution_options(include_deleted=True)`.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import event, func, or_, select, update
from sqlalchemy.orm import Session, aliased, with_loader_criteria

from finora.core.current import current
from finora.models import Account, BankLine, Entry

INCLUDE = "include_deleted"
WITH_DELETED = {INCLUDE: True}


@event.listens_for(Session, "do_orm_execute")
def _hide_deleted(state) -> None:
    if (state.is_select and not state.is_column_load and not state.is_relationship_load
            and not state.execution_options.get(INCLUDE, False)):
        state.statement = state.statement.options(
            with_loader_criteria(Entry, Entry.deleted_at.is_(None), include_aliases=True))


def get(s: Session, entry_id: int) -> Entry | None:
    """O lançamento mesmo que esteja na lixeira."""
    return s.get(Entry, entry_id, execution_options=WITH_DELETED)


def move(s: Session, entries: list[Entry]) -> int:
    """Manda para a lixeira (sem commit). A conciliação solta as linhas do extrato ligadas a eles."""
    now = datetime.now().replace(microsecond=0)
    ids = [e.id for e in entries]
    for e in entries:
        e.deleted_at = now
        e.deleted_by = (current.user_name or "")[:80] or None
    if ids:
        s.execute(update(BankLine).where(BankLine.entry_id.in_(ids)).values(entry_id=None, status="pending"))
    return len(entries)


def restore(s: Session, entry_ids: list[int]) -> int:
    n = 0
    for i in entry_ids:
        e = get(s, i)
        if e is not None and e.deleted_at is not None:
            e.deleted_at = None
            e.deleted_by = None
            n += 1
    s.commit()
    return n


@dataclass(frozen=True)
class TrashView:
    id: int
    kind: str
    description: str
    amount: Decimal              # na moeda da conta, com sinal (despesa negativa)
    currency: str
    due_date: object
    account: str
    deleted_at: datetime
    deleted_by: str


def list_trash(s: Session, entity_id: int, search: str = "") -> list[TrashView]:
    dest = aliased(Account)
    q = (select(Entry, Account.name, Account.currency, dest.name)
         .join(Account, Entry.account_id == Account.id)
         .outerjoin(dest, Entry.dest_account_id == dest.id)
         .where(Entry.entity_id == entity_id, Entry.deleted_at.is_not(None))
         .order_by(Entry.deleted_at.desc(), Entry.id.desc())
         .execution_options(**WITH_DELETED))
    if search.strip():
        like = f"%{search.strip().lower()}%"
        q = q.where(or_(func.lower(Entry.description).like(like), func.lower(Account.name).like(like)))
    out = []
    for e, acc, cur, dest_name in s.execute(q):
        account = f"{acc} → {dest_name}" if e.kind == "transfer" and dest_name else acc
        out.append(TrashView(e.id, e.kind, e.description or "", -e.amount if e.kind == "expense" else e.amount,
                             cur, e.due_date, account, e.deleted_at, e.deleted_by or "—"))
    return out


def count(s: Session, entity_id: int) -> int:
    return s.scalar(select(func.count(Entry.id)).where(Entry.entity_id == entity_id, Entry.deleted_at.is_not(None))
                    .execution_options(**WITH_DELETED)) or 0
