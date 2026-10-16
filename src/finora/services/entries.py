"""Lançamentos: receitas, despesas, transferências e ajustes de saldo, com recorrência e parcelamento.

Convenções:
- `amount` é sempre positivo; o tipo define o sinal (INFLOW entra na conta, OUTFLOW sai).
- Transferência sai de `account_id` e entra em `dest_account_id`; não tem categoria nem contato.
- Ajuste de saldo (depósito/retirada, as "movimentações bancárias" D/R do MCC): mexe no saldo e no extrato da
  conta, mas não é receita nem despesa — fica fora da DRE e dos relatórios de resultado. Sem categoria nem contato.
- Lançamentos de uma recorrência/parcelamento compartilham `series_id`.
"""
import calendar
import re
import uuid
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from finora.core.money import CENT
from finora.models import Account, Category, Contact, CostCenter, Entry
from finora.services import contacts, scope

KINDS = {"expense": "Despesa", "income": "Receita", "transfer": "Transferência", "deposit": "Depósito",
         "withdrawal": "Retirada"}
RESULT_KINDS = ("income", "expense")        # entram na DRE e nos relatórios de resultado
ADJUST_KINDS = ("deposit", "withdrawal")    # ajuste de saldo: só saldo e extrato
INFLOW = ("income", "deposit")              # somam no saldo da conta (transferência: só no destino)
NO_CATEGORY = ("transfer",) + ADJUST_KINDS  # sem categoria, centro de custo nem contato

# Intervalo entre ocorrências: chave -> (rótulo, meses, dias). Os mesmos do parcelamento do MCC
# (diária, semanal, quinzenal = 15 dias, mensal, bimestral, trimestral, semestral, anual).
INTERVALS = {
    "daily": ("Todo dia", 0, 1),
    "weekly": ("Toda semana", 0, 7),
    "biweekly": ("A cada 15 dias", 0, 15),
    "monthly": ("Todo mês", 1, 0),
    "bimonthly": ("A cada 2 meses", 2, 0),
    "quarterly": ("A cada 3 meses", 3, 0),
    "semiannual": ("A cada 6 meses", 6, 0),
    "yearly": ("Todo ano", 12, 0),
}
# Repetição: "none", "installments" (divide o valor; o intervalo vem de EntryData.every) ou um intervalo acima
# (repete o mesmo valor). chave -> (rótulo, meses, dias)
REPEATS = {"none": ("Não repete", 0, 0), "installments": ("Parcelado", 1, 0), **INTERVALS}
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


def occurrence(start: date, repeat: str, i: int, every: str = "monthly") -> date:
    """Data da i-ésima ocorrência (0 = a primeira). No parcelado, o intervalo é `every`."""
    _label, months, days = INTERVALS[every] if repeat == "installments" else REPEATS[repeat]
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
    cost_center_id: int | None = None
    cost_center: str | None = None
    currency: str = "BRL"                 # moeda da conta
    base_amount: Decimal | None = None    # valor na moeda principal
    dest_amount: Decimal | None = None    # transferência entre moedas: quanto chega no destino
    dest_currency: str | None = None
    notes: str | None = None              # observações
    original_amount: Decimal | None = None  # valor previsto, quando o pago saiu diferente

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"

    @property
    def paid_difference(self) -> Decimal:
        """Pago - previsto: positivo = juros/multa, negativo = desconto (0 se pagou o previsto)."""
        return self.amount - self.original_amount if self.original_amount is not None else Decimal(0)

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
            return {"income": "Recebido", "expense": "Pago", "transfer": "Transferido", "deposit": "Depositado",
                    "withdrawal": "Retirado"}[self.kind]
        if self.is_late(today):
            return "Atrasado"
        return {"income": "A receber", "expense": "A pagar", "transfer": "A transferir", "deposit": "A depositar",
                "withdrawal": "A retirar"}[self.kind]

    @property
    def signed_amount(self) -> Decimal:
        """Valor com sinal para a lista: entrada positiva, saída negativa (transferência: positivo, neutro)."""
        return -self.amount if self.kind in ("expense", "withdrawal") else self.amount


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
        select(Entry, Account.name, dest.name, Category.name, Contact.name, CostCenter.name, Account.currency,
               dest.currency)
        .join(Account, Entry.account_id == Account.id)
        .outerjoin(dest, Entry.dest_account_id == dest.id)
        .outerjoin(Category, Entry.category_id == Category.id)
        .outerjoin(Contact, Entry.contact_id == Contact.id)
        .outerjoin(CostCenter, Entry.cost_center_id == CostCenter.id)
        .where(Entry.entity_id == entity_id, Entry.status != "canceled")
    )


def to_view(row) -> EntryView:
    e, acc, dest, cat, ct, cc, cur, dest_cur = row
    return EntryView(e.id, e.kind, e.description or "", Decimal(e.amount), e.due_date, e.paid_date, e.status,
                     e.account_id, acc, e.dest_account_id, dest, e.category_id, cat, ct, e.document_no,
                     e.installment, e.series_id, e.competence_date, e.cost_center_id, cc, cur,
                     Decimal(e.base_amount) if e.base_amount is not None else Decimal(e.amount),
                     Decimal(e.dest_amount) if e.dest_amount is not None else None, dest_cur, e.notes,
                     Decimal(e.original_amount) if e.original_amount is not None else None)


# Período da lista (como no IgnControl): o mês do cabeçalho, trimestres, semestres, o ano ou tudo
PERIODS = {"month": "Mês", "q1": "1º trimestre", "q2": "2º trimestre", "q3": "3º trimestre", "q4": "4º trimestre",
           "s1": "1º semestre", "s2": "2º semestre", "year": "Ano todo", "all": "Todo o período"}
DATE_FIELDS = {"due": "Vencimento", "competence": "Competência (data da compra)", "paid": "Pagamento"}
KIND_FILTERS = {"": "Todos os tipos", "income": "Só receitas", "expense": "Só despesas",
                "transfer": "Só transferências", "adjust": "Só ajustes de saldo (depósitos e retiradas)"}


def period_range(year: int, month: int, period: str) -> tuple[date, date] | None:
    """Datas do período (None = todo o período)."""
    if period == "all":
        return None
    if period.startswith("q"):
        q = int(period[1])
        return date(year, 3 * q - 2, 1), month_range(year, 3 * q)[1]
    if period.startswith("s"):
        h = int(period[1])
        return date(year, 6 * h - 5, 1), month_range(year, 6 * h)[1]
    if period == "year":
        return date(year, 1, 1), date(year, 12, 31)
    return month_range(year, month)


def list_entries(s: Session, entity_id: int, *, year: int, month: int, filter: str = "all",
                 search: str = "", today: date | None = None, account_id: int | None = None,
                 category_id: int | None = None, period: str = "month", date_field: str = "due",
                 kind: str = "", contact_id: int | None = None, cost_center_id: int | None = None) -> list[EntryView]:
    """Lançamentos do período (pelo vencimento, por padrão). 'Atrasados' ignora o período; 'Pagos' usa a data do
    pagamento.

    `period`: month (o mês do cabeçalho), q1..q4, s1/s2, year ou all. `date_field`: due | competence | paid.
    `account_id`: só os dessa conta (inclui transferências que entram nela).
    `category_id`: só os dessa categoria; se for um grupo, inclui as subcategorias dele."""
    today = today or date.today()
    span = period_range(year, month, period)
    col = {"competence": Entry.competence_date, "paid": Entry.paid_date}.get(date_field, Entry.due_date)
    q = query(entity_id)
    if filter == "late":
        q = q.where(Entry.status == "pending", Entry.due_date < today)
    elif filter == "paid":
        q = q.where(Entry.status == "paid")
        if span:
            q = q.where(Entry.paid_date.between(*span))
    else:
        if span:
            q = q.where(col.between(*span))
        if filter == "receivable":
            q = q.where(Entry.status == "pending", Entry.kind == "income")
        elif filter == "payable":
            q = q.where(Entry.status == "pending", Entry.kind == "expense")
    if kind in ("income", "expense", "transfer"):
        q = q.where(Entry.kind == kind)
    elif kind == "adjust":
        q = q.where(Entry.kind.in_(ADJUST_KINDS))
    if contact_id:
        q = q.where(Entry.contact_id == contact_id)
    if cost_center_id:
        q = q.where(Entry.cost_center_id == cost_center_id)
    if account_id:
        q = q.where(or_(Entry.account_id == account_id, Entry.dest_account_id == account_id))
    if category_id:
        ids = [category_id] + list(s.scalars(select(Category.id).where(Category.parent_id == category_id)))
        q = q.where(Entry.category_id.in_(ids))
    if search.strip():
        like = f"%{search.strip().lower()}%"
        q = q.where(or_(func.lower(Entry.description).like(like), func.lower(Contact.name).like(like),
                        func.lower(Category.name).like(like), func.lower(Entry.document_no).like(like),
                        func.lower(Entry.notes).like(like)))
    q = q.order_by(Entry.due_date, Entry.id)
    return [to_view(r) for r in s.execute(q)]


def get(s: Session, entry_id: int) -> EntryView:
    return to_view(s.execute(query(s.get(Entry, entry_id).entity_id).where(Entry.id == entry_id)).one())


def month_totals(s: Session, entity_id: int, year: int, month: int) -> Totals:
    """Em aberto no mês. Faturas de cartão a pagar que vencem no mês entram em "a pagar"."""
    from finora.services import cards
    first, last = month_range(year, month)
    base = select(func.coalesce(func.sum(Entry.base_amount), 0)).where(
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
    cost_center_id: int | None = None
    dest_amount: Decimal | None = None     # transferência entre contas de moedas diferentes
    notes: str | None = None               # observações (também na transferência)
    every: str = "monthly"                 # parcelado: intervalo entre as parcelas (INTERVALS)
    # parcelado: todas as parcelas com a competência (data da DRE) da 1ª, como o MCC faz por padrão.
    # Desligado, cada parcela conta no mês em que vence. Não vale no cartão (lá a data é a da compra).
    competence_first: bool = False


MAX_NOTES = 1000


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
        if dest.currency != acc.currency and (d.dest_amount is None or d.dest_amount <= 0):
            raise ValueError(f"As contas têm moedas diferentes: informe quanto chega em {dest.name} "
                             f"({dest.currency}).")
    elif d.kind in ADJUST_KINDS:
        from finora.services import cards
        if cards.is_configured(acc):
            raise ValueError("Depósito e retirada não valem no cartão de crédito: use uma conta ou o caixa.")
    elif d.category_id is not None:
        cat = s.get(Category, d.category_id)
        if not scope.category_visible(s, cat, entity_id):
            raise ValueError("Categoria inválida.")
        if cat.kind != d.kind:
            raise ValueError("Essa categoria é de " + ("receita." if cat.kind == "income" else "despesa."))
    if d.cost_center_id is not None and d.kind not in NO_CATEGORY:
        cc = s.get(CostCenter, d.cost_center_id)
        if not scope.visible(cc, entity_id):
            raise ValueError("Centro de custo inválido.")
    if not d.description.strip():
        raise ValueError("Escreva uma descrição (ex.: Conta de luz).")
    if len((d.notes or "").strip()) > MAX_NOTES:
        raise ValueError(f"As observações podem ter até {MAX_NOTES} caracteres.")
    if d.repeat not in REPEATS:
        raise ValueError("Repetição inválida.")
    if d.repeat == "installments" and d.every not in INTERVALS:
        raise ValueError("Intervalo das parcelas inválido.")
    if d.repeat != "none" and not 2 <= d.times <= MAX_REPEAT:
        raise ValueError(f"Escolha de 2 a {MAX_REPEAT} vezes.")


def _on_card(s: Session, d: EntryData) -> bool:
    from finora.services import cards
    return d.kind in RESULT_KINDS and cards.is_configured(s.get(Account, d.account_id))


def _set_dates(s: Session, e: Entry, d: EntryData, when: date, paid_first: bool,
               competence: date | None = None) -> None:
    """Datas e situação. Compra/estorno num cartão configurado vai direto para a fatura certa.
    Fora do cartão, `when` é o vencimento e a competência é `competence` (padrão: o próprio vencimento)."""
    from finora.services import cards
    acc = s.get(Account, d.account_id)
    if _on_card(s, d):
        _closing, due = cards.statement_for(when, acc.closing_day, acc.due_day)
        e.competence_date, e.due_date = when, due
        e.status, e.paid_date = cards.CARD_STATUS, due
        return
    e.due_date, e.competence_date = when, competence or when
    if paid_first and d.paid:
        e.status, e.paid_date = "paid", d.paid_date or when
    else:
        e.status, e.paid_date = "pending", None


_INSTALLMENT_SUFFIX = re.compile(r"\s*\d+/\d+$")


def installment_doc(doc: str | None, installment: str | None) -> str | None:
    """Nº do documento de uma parcela, como no MCC: "NF-4521" -> "NF-4521 2/3". Sem documento continua vazio
    (a parcela já aparece ao lado da descrição). Um sufixo n/N que já esteja lá é trocado, não repetido."""
    base = _INSTALLMENT_SUFFIX.sub("", (doc or "").strip())
    if not installment:
        return (doc or "").strip() or None
    return f"{base} {installment}" if base else None


def _apply(e: Entry, d: EntryData, entity_id: int, contact_id: int | None) -> None:
    transfer = d.kind == "transfer"
    bare = d.kind in NO_CATEGORY
    e.kind = d.kind
    e.description = d.description.strip()
    e.account_id = d.account_id
    e.dest_account_id = d.dest_account_id if transfer else None
    e.dest_amount = d.dest_amount if transfer and d.dest_amount else None
    e.category_id = None if bare else d.category_id
    e.cost_center_id = None if bare else d.cost_center_id
    e.contact_id = None if bare else contact_id
    e.document_no = (d.document_no or "").strip() or None
    e.notes = (d.notes or "").strip() or None


def create(s: Session, entity_id: int, d: EntryData) -> list[int]:
    """Cria 1 lançamento, ou a série inteira (recorrência/parcelas). Só o 1º pode nascer pago."""
    _validate(s, entity_id, d)
    inactive = [a for a in (d.account_id, d.dest_account_id) if a and not s.get(Account, a).is_active]
    if inactive:
        raise ValueError("Essa conta está inativa. Ative-a em Contas para usar em lançamentos novos.")
    contact_id = None if d.kind in NO_CATEGORY else contacts.get_or_create(s, entity_id, d.contact, d.kind)
    n = 1 if d.repeat == "none" else d.times
    amounts = split(d.amount, n) if d.repeat == "installments" else [d.amount] * n
    series = uuid.uuid4().hex if n > 1 else None
    competence = d.due_date if d.repeat == "installments" and d.competence_first else None
    ids = []
    try:
        for i in range(n):
            e = Entry(entity_id=entity_id)
            _apply(e, d, entity_id, contact_id)
            e.amount = amounts[i]
            _set_dates(s, e, d, occurrence(d.due_date, d.repeat, i, d.every) if n > 1 else d.due_date, i == 0,
                       competence)
            e.series_id = series
            e.installment = f"{i + 1}/{n}" if d.repeat == "installments" else None
            e.document_no = installment_doc(e.document_no, e.installment)
            s.add(e)
            s.flush()
            ids.append(e.id)
        s.commit()
    except Exception:
        s.rollback()
        raise
    return ids


def repeat_next_month(s: Session, entry_ids: list[int]) -> list[int]:
    """"Repetir no mês seguinte" do MCC: para cada lançamento, uma cópia avulsa e em aberto com a data 1 mês
    depois (no cartão, a data da compra). Vai o valor previsto (sem juros/desconto da baixa); o "n/N" do documento
    de uma parcela não é copiado. Retorna os ids novos, na ordem."""
    rows = [s.get(Entry, i) for i in entry_ids]
    for e in rows:
        for a in (e.account_id, e.dest_account_id):
            if a and not s.get(Account, a).is_active:
                raise ValueError(f"\"{e.description}\" usa uma conta inativa. Ative-a em Contas para repetir.")
    out = []
    for e in rows:
        start = e.competence_date if e.status == "card" and e.competence_date else e.due_date
        contact = s.get(Contact, e.contact_id).name if e.contact_id else None
        doc = _INSTALLMENT_SUFFIX.sub("", e.document_no or "") if e.installment else e.document_no
        out += create(s, e.entity_id, EntryData(
            kind=e.kind, description=e.description or "", due_date=add_months(start, 1), account_id=e.account_id,
            amount=Decimal(e.original_amount if e.original_amount is not None else e.amount),
            dest_account_id=e.dest_account_id, category_id=e.category_id, contact=contact, document_no=doc,
            cost_center_id=e.cost_center_id, notes=e.notes,
            dest_amount=Decimal(e.dest_amount) if e.dest_amount is not None else None))
    return out


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
    contact_id = None if d.kind in NO_CATEGORY else contacts.get_or_create(s, e.entity_id, d.contact, d.kind)
    card = _on_card(s, d)
    try:
        targets = [e] + ([x for x in _following(s, e) if x.id != e.id and _open(x)]
                         if scope == "following" else [])
        # Competência separada do vencimento (parcelado na data da compra): continua onde estava.
        own_competence = {x.id: x.competence_date for x in targets
                          if x.status != "card" and x.competence_date != x.due_date}
        for x in targets:
            _apply(x, d, e.entity_id, contact_id)
            x.document_no = installment_doc(x.document_no, x.installment)
            x.amount = d.amount
            if x is not e:   # os próximos mantêm a própria data; só recalcula a fatura se mudou de conta
                when = x.competence_date if card or x.status == "card" else x.due_date
                _set_dates(s, x, d, when, False, None if card else own_competence.get(x.id))
        _set_dates(s, e, d, d.due_date, True, None if card else own_competence.get(e.id))
        s.commit()
    except Exception:
        s.rollback()
        raise
    return len(targets)


DELETE_SCOPES = ("one", "following", "open", "all")


@dataclass(frozen=True)
class SeriesInfo:
    total: int                 # lançamentos da série (fora os da lixeira)
    open: int                  # quantos ainda em aberto, em qualquer data
    following_open: int        # em aberto depois deste


def series_info(s: Session, entry_id: int) -> SeriesInfo:
    e = s.get(Entry, entry_id)
    if not e.series_id:
        return SeriesInfo(1, int(_open(e)), 0)
    rows = list(s.scalars(select(Entry).where(Entry.series_id == e.series_id)))
    return SeriesInfo(len(rows), sum(_open(x) for x in rows), in_series(s, entry_id))


def delete(s: Session, entry_id: int, scope: str = "one") -> list[int]:
    """Manda para a lixeira (como o FMultDelMov do MCC):
    - one: só este;
    - following: este e os próximos ainda não pagos da série;
    - open: todos os ainda não pagos da série, antes e depois deste;
    - all: a série inteira, pagos inclusive.
    Nada sai do banco: dá para restaurar (services/trash). Retorna os ids, para o "Desfazer"."""
    from finora.services import trash
    if scope not in DELETE_SCOPES:
        raise ValueError("Opção de exclusão inválida.")
    e = s.get(Entry, entry_id)
    if scope == "following":
        targets = [e] + [x for x in _following(s, e) if x.id != e.id and _open(x)]
    elif scope in ("open", "all") and e.series_id:
        q = select(Entry).where(Entry.series_id == e.series_id).order_by(Entry.due_date, Entry.id)
        targets = [x for x in s.scalars(q) if scope == "all" or _open(x)]
    else:
        targets = [e]
    ids = [x.id for x in targets]
    try:
        trash.move(s, targets)
        s.commit()
    except Exception:
        s.rollback()
        raise
    return ids


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
    """Marca como pago (só a data) ou volta para em aberto. Voltar não desfaz um valor pago diferente: o
    lançamento fica com o valor pago e o previsto guardado, como o estorno do MCC."""
    e = s.get(Entry, entry_id)
    if e.status == "card":
        raise ValueError("Compras no cartão são pagas pela fatura (em Contas › Faturas).")
    e.status, e.paid_date = ("paid", when or date.today()) if paid else ("pending", None)
    s.commit()


def pay(s: Session, entry_id: int, when: date | None = None, *, amount: Decimal | None = None,
        account_id: int | None = None, note: str | None = None) -> None:
    """Baixa completa (FBaixa do MCC): pago/recebido na data `when`, com o valor que de fato saiu ou entrou
    (juros, multa ou desconto), a conta usada e uma observação, que vai para o fim das observações.
    O valor previsto fica em `original_amount` (relatório de juros e descontos).
    Na transferência e no ajuste de saldo só a data muda; no cartão, o pagamento é pela fatura."""
    from finora.services import cards
    e = s.get(Entry, entry_id)
    if e.status == "card":
        raise ValueError("Compras no cartão são pagas pela fatura (em Contas › Faturas).")
    if e.status == "paid":
        raise ValueError("Esse lançamento já está pago.")
    if amount is not None and amount <= 0:
        raise ValueError("O valor pago precisa ser maior que zero.")
    new_amount = amount is not None and amount != Decimal(e.amount)
    new_account = account_id is not None and account_id != e.account_id
    if e.kind in NO_CATEGORY and (new_amount or new_account):
        raise ValueError("Na transferência e no ajuste de saldo só a data muda na baixa. Para mudar valor ou conta, "
                         "edite o lançamento.")
    if new_account:
        acc = s.get(Account, account_id)
        if acc is None or acc.entity_id != e.entity_id or not acc.is_active:
            raise ValueError("Escolha uma conta ativa.")
        if cards.is_configured(acc):
            raise ValueError("Para pagar com o cartão, lance a compra no cartão de crédito.")
    note = (note or "").strip()
    notes = f"{e.notes}\n{note}" if e.notes and note else (note or e.notes)
    if notes and len(notes) > MAX_NOTES:
        raise ValueError(f"As observações podem ter até {MAX_NOTES} caracteres.")
    try:
        if new_account:
            e.account_id = account_id
        if new_amount:
            previsto = e.original_amount if e.original_amount is not None else e.amount
            e.amount = amount
            e.original_amount = None if Decimal(previsto) == amount else previsto
        e.notes = notes
        e.status, e.paid_date = "paid", when or date.today()
        s.commit()
    except Exception:
        s.rollback()
        raise


def in_series(s: Session, entry_id: int) -> int:
    """Quantos lançamentos pendentes vêm depois deste na série (0 se não é série)."""
    e = s.get(Entry, entry_id)
    return len([x for x in _following(s, e) if x.id != e.id and _open(x)])
