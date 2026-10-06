"""Cartão de crédito: faturas (fechamento, vencimento, total, pagamento).

Regras:
- Compra no cartão = despesa na conta do cartão. Ela vai para a fatura certa pela data da compra.
  Compras NO dia do fechamento ou depois já caem na fatura seguinte (o "melhor dia de compra").
- A compra fica com status "card" (lançada no cartão): não aparece como "a pagar" sozinha.
  `competence_date` = data da compra; `due_date` = vencimento da fatura; `paid_date` = vencimento da fatura
  (é quando o dinheiro sai do bolso — usado na DRE por regime de caixa).
- Receita na conta do cartão (estorno) abate da fatura.
- Pagar a fatura = transferência de outra conta para o cartão, com `due_date` = vencimento da fatura.
"""
import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core.money import CENT
from finora.models import Account, Entry
from finora.services import entries

ZERO = Decimal("0.00")
CARD_STATUS = "card"
STATUS_LABELS = {"future": "Futura", "open": "Aberta", "closed": "Fechada", "late": "Atrasada", "paid": "Paga",
                 "empty": "Sem gastos"}


def _day(y: int, m: int, d: int) -> date:
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def _next_month(d: date) -> tuple[int, int]:
    return (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)


def is_configured(acc: Account) -> bool:
    return acc.kind == "card" and bool(acc.closing_day) and bool(acc.due_day)


def statement_dates(closing_day: int, due_day: int, year: int, month: int) -> tuple[date, date]:
    """(fechamento, vencimento) da fatura que FECHA no mês informado.
    Se o vencimento for depois do fechamento no mesmo mês (ex.: fecha 5, vence 15), vence no mesmo mês;
    senão (ex.: fecha 25, vence 5), vence no mês seguinte."""
    closing = _day(year, month, closing_day)
    if due_day > closing_day:
        return closing, _day(year, month, due_day)
    y, m = _next_month(closing)
    return closing, _day(y, m, due_day)


def statement_for(purchase: date, closing_day: int, due_day: int) -> tuple[date, date]:
    """Em qual fatura cai uma compra feita em `purchase`: (fechamento, vencimento)."""
    closing, due = statement_dates(closing_day, due_day, purchase.year, purchase.month)
    if purchase >= closing:                       # no dia do fechamento ou depois: próxima fatura
        y, m = _next_month(closing)
        closing, due = statement_dates(closing_day, due_day, y, m)
    return closing, due


@dataclass(frozen=True)
class Statement:
    account_id: int
    account: str
    opening: date          # 1º dia de compras desta fatura
    closing: date
    due: date
    charges: Decimal       # compras menos estornos
    paid: Decimal          # pagamentos feitos para esta fatura
    entries: int

    @property
    def remaining(self) -> Decimal:
        return max(self.charges - self.paid, ZERO)

    def status(self, today: date) -> str:
        if today < self.opening:
            return "future"                 # ex.: parcelas que caem em faturas que ainda nem abriram
        if self.charges <= 0:
            return "empty"
        if self.remaining <= 0:
            return "paid"
        if today < self.closing:
            return "open"
        return "late" if today > self.due else "closed"

    def status_label(self, today: date) -> str:
        return STATUS_LABELS[self.status(today)]

    @property
    def label(self) -> str:
        """Nome da fatura pelo mês do vencimento, como os bancos fazem: "nov/2026"."""
        return month_label(self.due)


def month_label(d: date) -> str:
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    return f"{meses[d.month - 1]}/{d.year}"


def _statement(s: Session, acc: Account, closing: date, due: date) -> Statement:
    prev_y, prev_m = (closing.year - 1, 12) if closing.month == 1 else (closing.year, closing.month - 1)
    prev_closing, _ = statement_dates(acc.closing_day, acc.due_day, prev_y, prev_m)
    rows = s.execute(select(Entry.kind, Entry.amount).where(
        Entry.account_id == acc.id, Entry.status == CARD_STATUS, Entry.due_date == due)).all()
    charges = sum((Decimal(a) if k == "expense" else -Decimal(a) for k, a in rows), ZERO)
    paid = s.scalar(select(func.coalesce(func.sum(Entry.amount), 0)).where(
        Entry.dest_account_id == acc.id, Entry.kind == "transfer", Entry.status == "paid", Entry.due_date == due))
    return Statement(acc.id, acc.name, prev_closing.fromordinal(prev_closing.toordinal() + 1), closing, due,
                     charges.quantize(CENT), Decimal(paid).quantize(CENT), len(rows))


def statement(s: Session, account_id: int, due: date) -> Statement:
    acc = s.get(Account, account_id)
    closing = next(c for c, d in _around(acc, due, 0, 0) if d == due)
    return _statement(s, acc, closing, due)


def _around(acc: Account, ref: date, back: int, ahead: int) -> list[tuple[date, date]]:
    out = []
    for i in range(-back - 1, ahead + 2):
        d = entries.add_months(ref.replace(day=1), i)
        out.append(statement_dates(acc.closing_day, acc.due_day, d.year, d.month))
    return out


def current(s: Session, account_id: int, today: date | None = None) -> Statement:
    """A fatura em que caem as compras de hoje (a "fatura aberta")."""
    acc = s.get(Account, account_id)
    closing, due = statement_for(today or date.today(), acc.closing_day, acc.due_day)
    return _statement(s, acc, closing, due)


def list_statements(s: Session, account_id: int, today: date | None = None, back: int = 6) -> list[Statement]:
    """Faturas do cartão: as últimas `back`, a aberta e as futuras que já têm compras (ex.: parcelas).
    Da mais nova para a mais antiga."""
    today = today or date.today()
    acc = s.get(Account, account_id)
    if not is_configured(acc):
        return []
    open_closing, open_due = statement_for(today, acc.closing_day, acc.due_day)
    last_due = s.scalar(select(func.max(Entry.due_date)).where(Entry.account_id == acc.id,
                                                               Entry.status == CARD_STATUS)) or open_due
    out, seen = [], set()
    first = entries.add_months(open_closing.replace(day=1), -back)
    i = 0
    while True:
        d = entries.add_months(first, i)
        closing, due = statement_dates(acc.closing_day, acc.due_day, d.year, d.month)
        i += 1
        if due in seen:
            continue
        seen.add(due)
        st = _statement(s, acc, closing, due)
        if due == open_due or st.charges != 0 or st.paid != 0:   # sem meses vazios na lista
            out.append(st)
        if due >= max(last_due, open_due):
            break
    return sorted(out, key=lambda x: x.due, reverse=True)


def open_statements(s: Session, entity_id: int, until: date, today: date | None = None) -> list[Statement]:
    """Faturas com saldo a pagar que vencem até `until`, de todos os cartões ativos. Inclui as atrasadas e
    também a que ainda está aberta (ela vai fechar e vencer dentro do período)."""
    today = today or date.today()
    out = []
    for acc in s.scalars(select(Account).where(Account.entity_id == entity_id, Account.kind == "card",
                                               Account.is_active)):
        if not is_configured(acc):
            continue
        for st in list_statements(s, acc.id, today, back=12):
            if st.remaining > 0 and st.due <= until:
                out.append(st)
    return sorted(out, key=lambda x: x.due)


def pay(s: Session, account_id: int, due: date, *, from_account_id: int, amount: Decimal,
        when: date | None = None) -> int:
    """Paga (total ou parte de) a fatura que vence em `due`, saindo de outra conta. Retorna o id."""
    acc = s.get(Account, account_id)
    if amount is None or amount <= 0:
        raise ValueError("O valor precisa ser maior que zero.")
    src = s.get(Account, from_account_id) if from_account_id else None
    if src is None or src.entity_id != acc.entity_id or src.id == acc.id:
        raise ValueError("Escolha de qual conta sai o dinheiro.")
    if src.kind == "card":
        raise ValueError("Não dá para pagar uma fatura com outro cartão.")
    e = Entry(entity_id=acc.entity_id, kind="transfer", account_id=src.id, dest_account_id=acc.id,
              amount=amount, description=f"Pagamento da fatura {acc.name} {month_label(due)}",
              competence_date=due, due_date=due, status="paid", paid_date=when or date.today())
    s.add(e)
    s.commit()
    return e.id


def available_limit(s: Session, account_id: int) -> Decimal | None:
    """Limite livre = limite + saldo (o saldo do cartão é negativo quando há dívida)."""
    from finora.services import accounts
    acc = s.get(Account, account_id)
    if acc.credit_limit is None:
        return None
    bal = next(a.balance for a in accounts.list_accounts(s, acc.entity_id, include_inactive=True) if a.id == acc.id)
    return (Decimal(acc.credit_limit) + bal).quantize(CENT)


def statement_entries(s: Session, account_id: int, due: date) -> list[entries.EntryView]:
    """Compras e estornos de uma fatura, pela data da compra."""
    acc = s.get(Account, account_id)
    q = (entries.query(acc.entity_id)
         .where(Entry.account_id == account_id, Entry.status == CARD_STATUS, Entry.due_date == due)
         .order_by(Entry.competence_date, Entry.id))
    return [entries.to_view(r) for r in s.execute(q)]


def due_between(s: Session, entity_id: int, first: date, last: date, today: date | None = None) -> list[Statement]:
    """Faturas (com gastos) que vencem entre `first` e `last`, de todos os cartões ativos."""
    out = []
    for acc in s.scalars(select(Account).where(Account.entity_id == entity_id, Account.kind == "card",
                                               Account.is_active)):
        if is_configured(acc):
            out += [st for st in list_statements(s, acc.id, today, back=14)
                    if first <= st.due <= last and st.charges > 0]
    return sorted(out, key=lambda x: x.due)
