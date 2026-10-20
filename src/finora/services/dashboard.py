"""Números do Dashboard. Tudo pelo vencimento (regime de competência), sem contar transferências."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from finora.core.money import CENT
from finora.models import Category, Entry
from finora.services import accounts, cards, entries, reports
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
    from finora.services.dre import NOT_RESULT
    return (Entry.category_id.is_(None)) | (Category.dre_group.is_(None)) | (Category.dre_group.not_in(NOT_RESULT))


def month_result(s: Session, entity_id: int, year: int, month: int) -> Decimal:
    """Sobra do mês: a mesma linha "= Sobra do mês" da DRE pessoal (competência), para nunca divergir."""
    return reports.dre(s, entity_id, [(year, month)]).row("sobra").total


def kpis(s: Session, entity_id: int, today: date | None = None) -> Kpis:
    today = today or date.today()
    accs = accounts.list_accounts(s, entity_id)
    horizon = today + timedelta(days=30)
    pending = (Entry.entity_id == entity_id) & (Entry.status == "pending") & (Entry.due_date <= horizon)

    def total(kind):
        return s.execute(select(func.sum(Entry.base_amount), func.count(Entry.id))
                         .where(pending, Entry.kind == kind)).one()

    rec, rec_n = total("income")
    pay, pay_n = total("expense")
    late_n = s.scalar(select(func.count(Entry.id)).where(
        Entry.entity_id == entity_id, Entry.status == "pending", Entry.kind == "expense", Entry.due_date < today))
    statements = cards.open_statements(s, entity_id, horizon, today)     # faturas de cartão a pagar
    pay = Decimal(pay or 0) + sum((st.remaining for st in statements), ZERO)
    pay_n += len(statements)
    late_n += sum(1 for st in statements if st.due < today)
    prev = entries.add_months(today.replace(day=1), -1)
    return Kpis(accounts.total_balance(accs), len(accounts.money_accounts(accs)), _d(rec), rec_n, _d(pay), pay_n, late_n,
                month_result(s, entity_id, today.year, today.month),
                month_result(s, entity_id, prev.year, prev.month))


def monthly_flow(s: Session, entity_id: int, months: int = 6, today: date | None = None) -> list[MonthFlow]:
    """Entradas e saídas dos últimos `months` meses (o atual é o último)."""
    today = today or date.today()
    start = entries.add_months(today.replace(day=1), -(months - 1))
    end = entries.month_range(today.year, today.month)[1]
    q = (select(Entry.competence_date, Entry.kind, Entry.base_amount)
         .where(Entry.entity_id == entity_id, Entry.kind.in_(("income", "expense")), Entry.status != "canceled",
                Entry.competence_date.between(start, end)))
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
         .where(Entry.status == "pending", Entry.kind.in_(("income", "expense")), Entry.due_date <= today + timedelta(days=days))
         .order_by(Entry.due_date, Entry.id).limit(limit))
    return [entries.to_view(r) for r in s.execute(q)]


def top_expenses(s: Session, entity_id: int, year: int, month: int, n: int = 5) -> list[tuple[str, Decimal]]:
    """Maiores despesas do mês por grupo de categoria (sem Investimentos/Reserva)."""
    first, last = entries.month_range(year, month)
    group = aliased(Category)
    name = func.coalesce(group.name, Category.name, "Sem categoria")
    q = (select(name, func.sum(Entry.base_amount))
         .select_from(Entry)
         .outerjoin(Category, Entry.category_id == Category.id)
         .outerjoin(group, Category.parent_id == group.id)
         .where(Entry.entity_id == entity_id, Entry.kind == "expense", Entry.status != "canceled",
                Entry.competence_date.between(first, last), _not_investment())
         .group_by(name).order_by(func.sum(Entry.base_amount).desc()).limit(n))
    return [(label, _d(v)) for label, v in s.execute(q)]


# ---------- caixa × competência e análise linear (Fase 3.12, do MCC) ----------
CA_PERIODS = {"today": "Hoje", "week": "Esta semana", "month": "Este mês", "custom": "Personalizado"}
LINEAR_STEPS = {"day": "Diária", "week": "Semanal", "month": "Mensal"}
REGIMES = {"cash": "Caixa", "accrual": "Competência"}


def ca_range(key: str, today: date | None = None) -> tuple[date, date]:
    """Hoje, a semana (segunda a domingo) ou o mês de hoje."""
    today = today or date.today()
    if key == "today":
        return today, today
    if key == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


@dataclass(frozen=True)
class RegimeTotals:
    income: Decimal
    expense: Decimal
    count: int

    @property
    def result(self) -> Decimal:
        return self.income - self.expense


@dataclass(frozen=True)
class CashAccrual:
    first: date
    last: date
    cash: RegimeTotals          # pago e recebido no período (pela data do pagamento)
    accrual: RegimeTotals       # vence (competência) no período, pago ou não — com os vencidos, se pedido
    overdue: RegimeTotals       # em aberto que venceram antes do período (já somados em accrual se pedido)


def _totals(s: Session, where) -> RegimeTotals:
    rows = s.execute(select(Entry.kind, func.sum(Entry.base_amount), func.count(Entry.id))
                     .where(where, Entry.kind.in_(entries.RESULT_KINDS)).group_by(Entry.kind)).all()
    by = {k: (_d(v), n) for k, v, n in rows}
    inc, n_inc = by.get("income", (ZERO, 0))
    exp, n_exp = by.get("expense", (ZERO, 0))
    return RegimeTotals(inc, exp, n_inc + n_exp)


def cash_vs_accrual(s: Session, entity_id: int, first: date, last: date, overdue: bool = False) -> CashAccrual:
    """Caixa: o que de fato entrou e saiu no período. Competência: o que vence no período, pago ou não (sem
    cancelados). overdue ("considerar vencidos", como no MCC): soma na competência o que venceu antes e continua em
    aberto. Valores na moeda principal; transferências e ajustes de saldo não entram."""
    mine = Entry.entity_id == entity_id
    cash = _totals(s, mine & (Entry.status == "paid") & Entry.paid_date.between(first, last))
    accrual = _totals(s, mine & (Entry.status != "canceled") & Entry.competence_date.between(first, last))
    late = _totals(s, mine & (Entry.status == "pending") & (Entry.due_date < first))
    if overdue:
        accrual = RegimeTotals(accrual.income + late.income, accrual.expense + late.expense,
                               accrual.count + late.count)
    return CashAccrual(first, last, cash, accrual, late)


@dataclass(frozen=True)
class LinearRow:
    start: date
    label: str
    income: Decimal
    expense: Decimal
    cumulative: Decimal         # resultado acumulado desde o início do período

    @property
    def result(self) -> Decimal:
        return self.income - self.expense


def _bucket(d: date, step: str) -> date:
    if step == "week":
        return d - timedelta(days=d.weekday())
    if step == "month":
        return d.replace(day=1)
    return d


def linear(s: Session, entity_id: int, first: date, last: date, step: str = "day",
           regime: str = "cash") -> list[LinearRow]:
    """Análise linear (MCC): receitas, despesas, resultado e acumulado por dia, semana (segunda a domingo) ou mês do
    período, no regime de caixa (data do pagamento) ou de competência (vencimento). Inclui os intervalos vazios."""
    if step not in LINEAR_STEPS or regime not in REGIMES:
        raise ValueError("Opção inválida.")
    when = Entry.paid_date if regime == "cash" else Entry.competence_date
    cond = (Entry.status == "paid") if regime == "cash" else (Entry.status != "canceled")
    q = (select(when, Entry.kind, Entry.base_amount)
         .where(Entry.entity_id == entity_id, Entry.kind.in_(entries.RESULT_KINDS), cond, when.between(first, last)))
    acc: dict[date, list] = {}
    for d, kind, amount in s.execute(q):
        acc.setdefault(_bucket(d, step), [ZERO, ZERO])[0 if kind == "income" else 1] += _d(amount)
    out, cur, total = [], _bucket(first, step), ZERO
    months = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
    while cur <= last:
        inc, exp = acc.get(cur, [ZERO, ZERO])
        total += inc - exp
        if step == "month":
            label = f"{months[cur.month - 1]}/{cur.year}"
        elif step == "week":
            label = f"{max(cur, first):%d/%m} a {min(cur + timedelta(days=6), last):%d/%m}"
        else:
            label = f"{cur:%d/%m}"
        out.append(LinearRow(cur, label, inc, exp, total))
        cur = (cur + timedelta(days=32)).replace(day=1) if step == "month" else \
            cur + timedelta(days=7 if step == "week" else 1)
    return out
