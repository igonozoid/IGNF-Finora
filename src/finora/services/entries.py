"""Lançamentos: receitas, despesas e transferências, com recorrência e parcelamento.

Convenções:
- `amount` é sempre positivo; o tipo (income/expense/transfer) define o sinal.
- Transferência sai de `account_id` e entra em `dest_account_id`; não tem categoria nem contato.
- Lançamentos de uma recorrência/parcelamento compartilham `series_id`.
"""
import calendar
import uuid
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from finora.core.money import CENT
from finora.models import Account, Category, Contact, Entry
from finora.services import contacts

KINDS = {"expense": "Despesa", "income": "Receita", "transfer": "Transferência"}

# Repetição: chave -> (rótulo, meses entre ocorrências, dias entre ocorrências)
REPEATS = {
    "none": ("Não repete", 0, 0),
    "installments": ("Parcelado", 1, 0),
    "monthly": ("Todo mês", 1, 0),
    "weekly": ("Toda semana", 0, 7),
    "yearly": ("Todo ano", 12, 0),
}
MAX_REPEAT = 360

FILTERS = {
    "all": "Todos",
    "receivable": "A receber",
    "payable": "A pagar",
    "late": "Atrasados",
    "paid": "Pagos",
}


# ---------- datas ----------
def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def occurrence(start: date, repeat: str, i: int) -> date:
    _label, months, days = REPEATS[repeat]
    if days:
        return date.fromordinal(start.toordinal() + days * i)
    return add_months(start, months * i)  # sempre a partir da 1ª data: 31/01 -> 28/02 -> 31/03


def split(total: Decimal, n: int) -> list[Decimal]:
    """Divide em n parcelas; os centavos que sobram vão na 1ª (100/3 = 33,34 + 33,33 + 33,33)."""
    part = (total / n).quantize(CENT, rounding=ROUND_DOWN)
    return [total - part * (n - 1)] + [part] * (n - 1)


# ---------- leitura ----------
@dataclass(frozen=True)
class EntryView:
    id: int
    kind: str
    description: str
    amount: Decimal
    due_date: date
    paid_date: date | None
    status: str                 # pending | paid | card (compra lançada no cartão de crédito)
    account_id: int
    account: str
    dest_account_id: int | None
    dest_account: str | None
    category_id: int | None
    category: str | None
    contact: str | None
    document_no: str | None
    installment: str | None
    series_id: str | None
    competence_date: date | None = None   # data da compra (cartão) / competência

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"

    @property
    def on_card(self) -> bool:
        return self.status == "card"

    def is_late(self, today: date) -> bool:
        return self.status == "pending" and self.due_date < today

    @property
    def is_recurring(self) -> bool:
        return self.series_id is not None and self.installment is None

    def status_label(self, today: date) -> str:
        if self.on_card:
            return "Estorno" if self.kind == "income" else "No cartão"
        if self.is_paid:
            return {"income": "Recebido", "expense": "Pago", "transfer": "Transferido"}[self.kind]
        if self.is_late(today):
            return "Atrasado"
        return {"income": "A receber", "expense": "A pagar", "transfer": "A transferir"}[self.kind]


@dataclass(frozen=True)
class Totals:
    receivable: Decimal
    payable: Decimal

    @property
    def balance(self) -> Decimal:
        return self.receivable - self.payable


def query(entity_id: int):
    dest = aliased(Account)
    return (
        select(Entry, Account.name, dest.name, Category.name, Contact.name)
        .join(Account, Entry.account_id == Account.id)
        .outerjoin(dest, Entry.dest_account_id == dest.id)
        .outerjoin(Category, Entry.category_id == Category.id)
        .outerjoin(Contact, Entry.contact_id == Contact.id)
        .where(Entry.entity_id == entity_id, Entry.status != "canceled")
    )


def to_view(row) -> EntryView:
    e, acc, dest, cat, ct = row
    return EntryView(e.id, e.kind, e.description or "", Decimal(e.amount), e.due_date, e.paid_date, e.status,
                     e.account_id, acc, e.dest_account_id, dest, e.category_id, cat, ct, e.document_no,
                     e.installment, e.series_id, e.competence_date)


def list_entries(s: Session, entity_id: int, *, year: int, month: int, filter: str = "all",
                 search: str = "", today: date | None = None, account_id: int | None = None,
                 category_id: int | None = None) -> list[EntryView]:
    """Lançamentos do mês (pelo vencimento). 'Atrasados' ignora o mês; 'Pagos' usa a data do pagamento.

    `account_id`: só os dessa conta (inclui transferências que entram nela).
    `category_id`: só os dessa categoria; se for um grupo, inclui as subcategorias dele."""
    today = today or date.today()
    first, last = month_range(year, month)
    q = query(entity_id)
    if filter == "late":
        q = q.where(Entry.status == "pending", Entry.due_date < today)
    elif filter == "paid":
        q = q.where(Entry.status == "paid", Entry.paid_date.between(first, last))
    else:
        q = q.where(Entry.due_date.between(first, last))
        if filter == "receivable":
            q = q.where(Entry.status == "pending", Entry.kind == "income")
        elif filter == "payable":
            q = q.where(Entry.status == "pending", Entry.kind == "expense")
    if account_id:
        q = q.where(or_(Entry.account_id == account_id, Entry.dest_account_id == account_id))
    if category_id:
        ids = [category_id] + list(s.scalars(select(Category.id).where(Category.parent_id == category_id)))
        q = q.where(Entry.category_id.in_(ids))
    if search.strip():
        like = f"%{search.strip().lower()}%"
        q = q.where(or_(func.lower(Entry.description).like(like), func.lower(Contact.name).like(like),
                        func.lower(Category.name).like(like), func.lower(Entry.document_no).like(like)))
    q = q.order_by(Entry.due_date, Entry.id)
    return [to_view(r) for r in s.execute(q)]


def get(s: Session, entry_id: int) -> EntryView:
    return to_view(s.execute(query(s.get(Entry, entry_id).entity_id).where(Entry.id == entry_id)).one())


def month_totals(s: Session, entity_id: int, year: int, month: int) -> Totals:
    """Em aberto no mês. Faturas de cartão a pagar que vencem no mês entram em "a pagar"."""
    from finora.services import cards
    first, last = month_range(year, month)
    base = select(func.coalesce(func.sum(Entry.amount), 0)).where(
        Entry.entity_id == entity_id, Entry.status == "pending", Entry.due_date.between(first, last))
    rec = s.scalar(base.where(Entry.kind == "income"))
    pay = Decimal(s.scalar(base.where(Entry.kind == "expense")))
    pay += sum((st.remaining for st in cards.open_statements(s, entity_id, last) if st.due >= first), Decimal(0))
    return Totals(Decimal(rec).quantize(CENT), pay.quantize(CENT))


# ---------- gravação ----------
@dataclass
class EntryData:
    kind: str
    description: str
    amount: Decimal
    due_date: date
    account_id: int
    dest_account_id: int | None = None
    category_id: int | None = None
    contact: str | None = None
    document_no: str | None = None
    paid: bool = False
    paid_date: date | None = None
    repeat: str = "none"
    times: int = 1


def _validate(s: Session, entity_id: int, d: EntryData) -> None:
    if d.kind not in KINDS:
        raise ValueError("Tipo de lançamento inválido.")
    if d.amount is None or d.amount <= 0:
        raise ValueError("O valor precisa ser maior que zero.")
    acc = s.get(Account, d.account_id) if d.account_id else None
    if acc is None or acc.entity_id != entity_id:
        raise ValueError("Escolha a conta.")
    if d.kind == "transfer":
        dest = s.get(Account, d.dest_account_id) if d.dest_account_id else None
        if dest is None or dest.entity_id != entity_id:
            raise ValueError("Escolha a conta de destino da transferência.")
        if dest.id == acc.id:
            raise ValueError("A conta de origem e a de destino precisam ser diferentes.")
    elif d.category_id is not None:
        cat = s.get(Category, d.category_id)
        if cat is None or cat.entity_id != entity_id:
            raise ValueError("Categoria inválida.")
        if cat.kind != d.kind:
            raise ValueError("Essa categoria é de " + ("receita." if cat.kind == "income" else "despesa."))
    if not d.description.strip():
        raise ValueError("Escreva uma descrição (ex.: Conta de luz).")
    if d.repeat not in REPEATS:
        raise ValueError("Repetição inválida.")
    if d.repeat != "none" and not 2 <= d.times <= MAX_REPEAT:
        raise ValueError(f"Escolha de 2 a {MAX_REPEAT} vezes.")


def _set_dates(s: Session, e: Entry, d: EntryData, when: date, paid_first: bool) -> None:
    """Datas e situação. Compra/estorno num cartão configurado vai direto para a fatura certa."""
    from finora.services import cards
    acc = s.get(Account, d.account_id)
    if d.kind != "transfer" and cards.is_configured(acc):
        _closing, due = cards.statement_for(when, acc.closing_day, acc.due_day)
        e.competence_date, e.due_date = when, due
        e.status, e.paid_date = cards.CARD_STATUS, due
    elif paid_first and d.paid:
        e.due_date = e.competence_date = when
        e.status, e.paid_date = "paid", d.paid_date or when
    else:
        e.due_date = e.competence_date = when
        e.status, e.paid_date = "pending", None


def _apply(e: Entry, d: EntryData, entity_id: int, contact_id: int | None) -> None:
    transfer = d.kind == "transfer"
    e.kind = d.kind
    e.description = d.description.strip()
    e.account_id = d.account_id
    e.dest_account_id = d.dest_account_id if transfer else None
    e.category_id = None if transfer else d.category_id
    e.contact_id = None if transfer else contact_id
    e.document_no = (d.document_no or "").strip() or None


def create(s: Session, entity_id: int, d: EntryData) -> list[int]:
    """Cria 1 lançamento, ou a série inteira (recorrência/parcelas). Só o 1º pode nascer pago."""
    _validate(s, entity_id, d)
    inactive = [a for a in (d.account_id, d.dest_account_id) if a and not s.get(Account, a).is_active]
    if inactive:
        raise ValueError("Essa conta está inativa. Ative-a em Contas para usar em lançamentos novos.")
    contact_id = None if d.kind == "transfer" else contacts.get_or_create(s, entity_id, d.contact, d.kind)
    n = 1 if d.repeat == "none" else d.times
    amounts = split(d.amount, n) if d.repeat == "installments" else [d.amount] * n
    series = uuid.uuid4().hex if n > 1 else None
    ids = []
    try:
        for i in range(n):
            e = Entry(entity_id=entity_id)
            _apply(e, d, entity_id, contact_id)
            e.amount = amounts[i]
            _set_dates(s, e, d, occurrence(d.due_date, d.repeat, i) if n > 1 else d.due_date, i == 0)
            e.series_id = series
            e.installment = f"{i + 1}/{n}" if d.repeat == "installments" else None
            s.add(e)
            s.flush()
            ids.append(e.id)
        s.commit()
    except Exception:
        s.rollback()
        raise
    return ids


def _following(s: Session, e: Entry) -> list[Entry]:
    """Este lançamento e os próximos da mesma série (pela data)."""
    if not e.series_id:
        return [e]
    q = select(Entry).where(Entry.series_id == e.series_id, Entry.due_date >= e.due_date).order_by(Entry.due_date)
    return list(s.scalars(q))


def _open(x: Entry) -> bool:
    """Ainda pode mudar junto com a série: em aberto, ou compra no cartão (a fatura é que se paga)."""
    return x.status != "paid"


def update(s: Session, entry_id: int, d: EntryData, scope: str = "one") -> int:
    """Altera o lançamento. Com scope='following', descrição/valor/conta/categoria/contato valem também
    para os próximos ainda não pagos da série (as datas deles não mudam). Retorna quantos mudaram."""
    e = s.get(Entry, entry_id)
    d = replace(d, repeat="none")
    _validate(s, e.entity_id, d)
    contact_id = None if d.kind == "transfer" else contacts.get_or_create(s, e.entity_id, d.contact, d.kind)
    try:
        targets = [e] + ([x for x in _following(s, e) if x.id != e.id and _open(x)]
                         if scope == "following" else [])
        for x in targets:
            _apply(x, d, e.entity_id, contact_id)
            x.amount = d.amount
            if x is not e:   # os próximos mantêm a própria data; só recalcula a fatura se mudou de conta
                _set_dates(s, x, d, x.competence_date, False)
        _set_dates(s, e, d, d.due_date, True)
        s.commit()
    except Exception:
        s.rollback()
        raise
    return len(targets)


def delete(s: Session, entry_id: int, scope: str = "one") -> int:
    """Exclui o lançamento (ou ele e os próximos ainda não pagos da série). Retorna quantos saíram."""
    e = s.get(Entry, entry_id)
    targets = [e] + ([x for x in _following(s, e) if x.id != e.id and _open(x)]
                     if scope == "following" else [])
    for x in targets:
        s.delete(x)
    s.commit()
    return len(targets)


def set_paid_many(s: Session, entry_ids: list[int], when: date | None = None) -> tuple[int, int]:
    """Marca vários como pagos/recebidos de uma vez. Pula os que já estão pagos e as compras no cartão
    (essas são pagas pela fatura). Retorna (quantos foram marcados, quantos foram pulados)."""
    done = skipped = 0
    for e in s.scalars(select(Entry).where(Entry.id.in_(entry_ids))):
        if e.status != "pending":
            skipped += 1
            continue
        e.status, e.paid_date = "paid", when or date.today()
        done += 1
    s.commit()
    return done, skipped


def set_paid(s: Session, entry_id: int, paid: bool, when: date | None = None) -> None:
    e = s.get(Entry, entry_id)
    if e.status == "card":
        raise ValueError("Compras no cartão são pagas pela fatura (em Contas › Faturas).")
    e.status, e.paid_date = ("paid", when or date.today()) if paid else ("pending", None)
    s.commit()


def in_series(s: Session, entry_id: int) -> int:
    """Quantos lançamentos pendentes vêm depois deste na série (0 se não é série)."""
    e = s.get(Entry, entry_id)
    return len([x for x in _following(s, e) if x.id != e.id and _open(x)])
