"""Números do Dashboard. Tudo pelo vencimento (regime de competência), sem contar transferências."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from finora.core.money import CENT
from finora.models import Category, Entry
from finora.services import accounts, entries, reports
from finora.services.entries import EntryView

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Kpis:
    balance: Decimal          # saldo das contas ativas
    accounts: int
    receivable: Decimal       # a receber até daqui a 30 dias (inclui atrasados)
    receivable_n: int
    payable: Decimal          # a pagar até daqui a 30 dias (inclui atrasados)
    payable_n: int
    late_n: int               # contas a pagar atrasadas
    result: Decimal           # sobra do mês: receitas - despesas, sem investimentos
    prev_result: Decimal      # sobra do mês anterior


@dataclass(frozen=True)
class MonthFlow:
    year: int
    month: int
    income: Decimal
    expense: Decimal


def _d(v) -> Decimal:
    return Decimal(v or 0).quantize(CENT)


def _not_investment():
    """Lançamento sem categoria, ou com categoria fora do grupo Investimentos/Reserva."""
    return (Entry.category_id.is_(None)) | (Category.dre_group.is_(None)) | (Category.dre_group != "investimentos")


def month_result(s: Session, entity_id: int, year: int, month: int) -> Decimal:
    """Sobra do mês: a mesma linha "= Sobra do mês" da DRE pessoal (competência), para nunca divergir."""
    return reports.dre(s, entity_id, [(year, month)]).row("sobra").total


def kpis(s: Session, entity_id: int, today: date | None = None) -> Kpis:
    today = today or date.today()
    accs = accounts.list_accounts(s, entity_id)
    horizon = today + timedelta(days=30)
    pending = (Entry.entity_id == entity_id) & (Entry.status == "pending") & (Entry.due_date <= horizon)

    def total(kind):
        return s.execute(select(func.sum(Entry.amount), func.count(Entry.id)).where(pending, Entry.kind == kind)).one()

    rec, rec_n = total("income")
    pay, pay_n = total("expense")
    late_n = s.scalar(select(func.count(Entry.id)).where(
        Entry.entity_id == entity_id, Entry.status == "pending", Entry.kind == "expense", Entry.due_date < today))
    prev = entries.add_months(today.replace(day=1), -1)
    return Kpis(accounts.total_balance(accs), len(accs), _d(rec), rec_n, _d(pay), pay_n, late_n,
                month_result(s, entity_id, today.year, today.month),
                month_result(s, entity_id, prev.year, prev.month))


def monthly_flow(s: Session, entity_id: int, months: int = 6, today: date | None = None) -> list[MonthFlow]:
    """Entradas e saídas dos últimos `months` meses (o atual é o último)."""
    today = today or date.today()
    start = entries.add_months(today.replace(day=1), -(months - 1))
    end = entries.month_range(today.year, today.month)[1]
    q = (select(Entry.due_date, Entry.kind, Entry.amount)
         .where(Entry.entity_id == entity_id, Entry.kind != "transfer", Entry.status != "canceled",
                Entry.due_date.between(start, end)))
    sums: dict[tuple, Decimal] = {}
    for due, kind, amount in s.execute(q):  # soma em Python: funciona em qualquer banco
        key = (due.year, due.month, kind)
        sums[key] = sums.get(key, ZERO) + Decimal(amount)
    out = []
    for i in range(months):
        d = entries.add_months(start, i)
        out.append(MonthFlow(d.year, d.month, _d(sums.get((d.year, d.month, "income"))),
                             _d(sums.get((d.year, d.month, "expense")))))
    return out


def due_soon(s: Session, entity_id: int, days: int = 7, today: date | None = None, limit: int = 8) -> list[EntryView]:
    """A pagar/receber que vencem até daqui a `days` dias, com os atrasados primeiro."""
    today = today or date.today()
    q = (entries.query(entity_id)
         .where(Entry.status == "pending", Entry.kind != "transfer", Entry.due_date <= today + timedelta(days=days))
         .order_by(Entry.due_date, Entry.id).limit(limit))
    return [entries.to_view(r) for r in s.execute(q)]


def top_expenses(s: Session, entity_id: int, year: int, month: int, n: int = 5) -> list[tuple[str, Decimal]]:
    """Maiores despesas do mês por grupo de categoria (sem Investimentos/Reserva)."""
    first, last = entries.month_range(year, month)
    group = aliased(Category)
    name = func.coalesce(group.name, Category.name, "Sem categoria")
    q = (select(name, func.sum(Entry.amount))
         .select_from(Entry)
         .outerjoin(Category, Entry.category_id == Category.id)
         .outerjoin(group, Category.parent_id == group.id)
         .where(Entry.entity_id == entity_id, Entry.kind == "expense", Entry.status != "canceled",
                Entry.due_date.between(first, last), _not_investment())
         .group_by(name).order_by(func.sum(Entry.amount).desc()).limit(n))
    return [(label, _d(v)) for label, v in s.execute(q)]
