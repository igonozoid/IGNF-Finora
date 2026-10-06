"""Relatórios: DRE pessoal e fluxo de caixa projetado.

DRE (linhas do CLAUDE.md): Receitas · (−) Moradia … (−) Outras despesas · = Sobra do mês ·
(−) Investimentos/Reserva · = Saldo livre.
- Regime de competência: tudo o que vence no mês (pago ou não), pela data de competência.
- Regime de caixa: só o que foi pago, pela data do pagamento.
- Sem categoria: receita vai para "Receitas"; despesa vai para "Outras despesas".
- Transferências entre contas não entram (o dinheiro não sai do seu bolso).
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from finora.core.money import CENT
from finora.models import Category, Entry
from finora.services import accounts, entries
from finora.services.dre import GROUPS

ZERO = Decimal("0.00")
EXPENSE_GROUPS = ["moradia", "alimentacao", "transporte", "saude", "educacao", "lazer", "outras"]
REGIMES = {"accrual": "Competência", "cash": "Caixa"}
PERIODS = {
    "3m": "Últimos 3 meses",
    "6m": "Últimos 6 meses",
    "12m": "Últimos 12 meses",
    "ytd": "Este ano",
    "last_year": "Ano passado",
}

HELP = {
    "receitas": "Tudo o que entrou: salário, renda extra, rendimentos…",
    "sobra": "Receitas menos as despesas do dia a dia. Mostra se o que você ganha cobre o que você gasta.",
    "investimentos": "Dinheiro guardado: reserva de emergência, investimentos, previdência.",
    "livre": "O que sobrou depois de pagar tudo e de guardar. Pode ir para a conta ou para um objetivo.",
}


# ---------- períodos ----------
def period_months(key: str, today: date | None = None) -> list[tuple[int, int]]:
    today = today or date.today()
    first = today.replace(day=1)
    if key == "ytd":
        return [(today.year, m) for m in range(1, today.month + 1)]
    if key == "last_year":
        return [(today.year - 1, m) for m in range(1, 13)]
    if key == "last_month":
        d = entries.add_months(first, -1)
        return [(d.year, d.month)]
    n = {"1m": 1, "3m": 3, "6m": 6, "12m": 12}[key]
    return [(d.year, d.month) for d in (entries.add_months(first, -i) for i in range(n - 1, -1, -1))]


# Períodos dos relatórios em lista (extrato, por categoria, por contato)
LIST_PERIODS = {"1m": "Este mês", "last_month": "Mês passado", **PERIODS}


def period_range(key: str, today: date | None = None) -> tuple[date, date]:
    months = period_months(key, today)
    return entries.month_range(*months[0])[0], entries.month_range(*months[-1])[1]


# ---------- DRE ----------
@dataclass
class DreRow:
    key: str
    label: str
    style: str                         # line | total | result | detail
    values: list[Decimal]
    help: str | None = None

    @property
    def total(self) -> Decimal:
        return sum(self.values, ZERO)


@dataclass
class DreReport:
    months: list[tuple[int, int]]
    rows: list[DreRow] = field(default_factory=list)

    def row(self, key: str) -> DreRow:
        return next(r for r in self.rows if r.key == key)

    def share(self, row: DreRow) -> Decimal | None:
        """Análise vertical: quanto a linha representa das receitas do período (%)."""
        base = self.row("receitas").total
        if base == 0:
            return None
        return (abs(row.total) * 100 / base).quantize(Decimal("0.1"))


def _movements(s: Session, entity_id: int, first: date, last: date, regime: str):
    """(data, tipo, valor, grupo da DRE, nome da subcategoria) dos lançamentos do período."""
    when = Entry.paid_date if regime == "cash" else Entry.competence_date
    q = (select(when, Entry.kind, Entry.base_amount, Category.dre_group, Category.name)
         .select_from(Entry).outerjoin(Category, Entry.category_id == Category.id)
         .where(Entry.entity_id == entity_id, Entry.kind != "transfer", when.between(first, last)))
    # Caixa: o que saiu do bolso. Compra no cartão sai no vencimento da fatura (paid_date = vencimento).
    q = q.where(Entry.status.in_(("paid", "card"))) if regime == "cash" else q.where(Entry.status != "canceled")
    return s.execute(q)


def dre(s: Session, entity_id: int, months: list[tuple[int, int]], regime: str = "accrual",
        details: bool = False) -> DreReport:
    first = entries.month_range(*months[0])[0]
    last = entries.month_range(*months[-1])[1]
    index = {ym: i for i, ym in enumerate(months)}
    n = len(months)
    groups: dict[str, list[Decimal]] = {g: [ZERO] * n for g in GROUPS}
    subs: dict[str, dict[str, list[Decimal]]] = {g: {} for g in GROUPS}

    for when, kind, amount, group, cat_name in _movements(s, entity_id, first, last, regime):
        if group not in GROUPS:
            group = "receitas" if kind == "income" else "outras"
        # Na DRE, receita soma e despesa subtrai — mesmo se alguém lançou despesa num grupo de receita.
        value = Decimal(amount) if kind == "income" else -Decimal(amount)
        i = index[(when.year, when.month)]
        groups[group][i] += value
        sub = subs[group].setdefault(cat_name or "Sem categoria", [ZERO] * n)
        sub[i] += value

    rep = DreReport(months)

    def add(key, style, values, label=None, help=None):
        rep.rows.append(DreRow(key, label or GROUPS.get(key, key), style, [v.quantize(CENT) for v in values], help))
        if details and style in ("line", "total") and key in subs:
            for name, vals in sorted(subs[key].items(), key=lambda kv: -abs(sum(kv[1], ZERO))):
                rep.rows.append(DreRow(f"{key}:{name}", name, "detail", [v.quantize(CENT) for v in vals]))

    add("receitas", "total", groups["receitas"], help=HELP["receitas"])
    for g in EXPENSE_GROUPS:
        add(g, "line", groups[g], label=f"(−) {GROUPS[g]}")
    sobra = [sum((groups[g][i] for g in ["receitas"] + EXPENSE_GROUPS), ZERO) for i in range(n)]
    add("sobra", "total", sobra, label="= Sobra do mês", help=HELP["sobra"])
    add("investimentos", "line", groups["investimentos"], label=f"(−) {GROUPS['investimentos']}",
        help=HELP["investimentos"])
    add("livre", "result", [sobra[i] + groups["investimentos"][i] for i in range(n)], label="= Saldo livre",
        help=HELP["livre"])
    return rep


# ---------- fluxo de caixa ----------
@dataclass
class FlowDay:
    day: date
    inflow: Decimal
    outflow: Decimal
    balance: Decimal
    items: list[str]


@dataclass
class CashFlow:
    start_balance: Decimal
    days: list[FlowDay]                  # um por dia do período (inclusive dias sem movimento)
    overdue: int                         # quantos atrasados foram trazidos para hoje

    @property
    def inflow(self) -> Decimal:
        return sum((d.inflow for d in self.days), ZERO)

    @property
    def outflow(self) -> Decimal:
        return sum((d.outflow for d in self.days), ZERO)

    @property
    def end_balance(self) -> Decimal:
        return self.days[-1].balance if self.days else self.start_balance

    @property
    def lowest(self) -> FlowDay | None:
        return min(self.days, key=lambda d: d.balance) if self.days else None


def cash_flow(s: Session, entity_id: int, days: int = 30, today: date | None = None) -> CashFlow:
    """Saldo de hoje nas contas + o que está em aberto, dia a dia. Atrasados entram em hoje."""
    today = today or date.today()
    end = today + timedelta(days=days - 1)
    start = accounts.total_balance(accounts.list_accounts(s, entity_id))
    q = (select(Entry.due_date, Entry.kind, Entry.base_amount, Entry.description)
         .where(Entry.entity_id == entity_id, Entry.status == "pending", Entry.kind != "transfer",
                Entry.due_date <= end)
         .order_by(Entry.due_date, Entry.id))
    by_day: dict[date, list] = {}
    overdue = 0
    for due, kind, amount, desc in s.execute(q):
        if due < today:
            overdue += 1
            due = today
        by_day.setdefault(due, []).append((kind, Decimal(amount), desc or ""))

    from finora.services import cards
    for st in cards.open_statements(s, entity_id, end, today):    # fatura do cartão = 1 saída no vencimento
        due = max(st.due, today)
        if st.due < today:
            overdue += 1
        by_day.setdefault(due, []).append(("expense", st.remaining, f"Fatura {st.account} {st.label}"))

    out, bal = [], start
    for i in range(days):
        d = today + timedelta(days=i)
        moves = by_day.get(d, [])
        inc = sum((a for k, a, _ in moves if k == "income"), ZERO)
        exp = sum((a for k, a, _ in moves if k == "expense"), ZERO)
        bal = bal + inc - exp
        out.append(FlowDay(d, inc.quantize(CENT), exp.quantize(CENT), bal.quantize(CENT), [m[2] for m in moves]))
    return CashFlow(start.quantize(CENT), out, overdue)


# ---------- extrato por conta ----------
@dataclass(frozen=True)
class StatementLine:
    entry_id: int
    day: date
    description: str
    category: str
    inflow: Decimal
    outflow: Decimal
    balance: Decimal


@dataclass(frozen=True)
class AccountStatement:
    opening: Decimal                 # saldo antes do 1º dia do período
    lines: list[StatementLine]

    @property
    def inflow(self) -> Decimal:
        return sum((x.inflow for x in self.lines), ZERO)

    @property
    def outflow(self) -> Decimal:
        return sum((x.outflow for x in self.lines), ZERO)

    @property
    def closing(self) -> Decimal:
        return self.lines[-1].balance if self.lines else self.opening


def _realized(account_id: int):
    """O que mexeu de verdade no saldo da conta: pagos e compras no cartão (data da compra)."""
    from sqlalchemy import or_
    return (or_(Entry.account_id == account_id, Entry.dest_account_id == account_id)
            & Entry.status.in_(("paid", "card")))


def _move(e: Entry, account_id: int) -> tuple[date, Decimal]:
    when = e.competence_date if e.status == "card" else e.paid_date
    amount = Decimal(e.amount)
    if e.kind == "transfer":
        if e.dest_account_id == account_id:
            return when, Decimal(e.dest_amount if e.dest_amount is not None else e.amount)
        return when, -amount
    return when, amount if e.kind == "income" else -amount


def account_statement(s: Session, account_id: int, first: date, last: date) -> AccountStatement:
    """Extrato: saldo anterior + cada movimento do período (pela data em que aconteceu) com o saldo corrido."""
    from finora.models import Account
    acc = s.get(Account, account_id)
    rows = s.execute(select(Entry, Category.name).outerjoin(Category, Entry.category_id == Category.id)
                     .where(_realized(account_id))).all()
    opening = Decimal(acc.opening_balance)
    moves = []
    for e, cat in rows:
        when, value = _move(e, account_id)
        if when < first:
            opening += value
        elif when <= last:
            label = "Transferência" if e.kind == "transfer" else (cat or "Sem categoria")
            moves.append((when, e.id, e.description or "", label, value))
    moves.sort(key=lambda m: (m[0], m[1]))
    lines, bal = [], opening
    for when, eid, desc, label, value in moves:
        bal += value
        lines.append(StatementLine(eid, when, desc, label, value if value > 0 else ZERO,
                                   -value if value < 0 else ZERO, bal.quantize(CENT)))
    return AccountStatement(opening.quantize(CENT), lines)


# ---------- por categoria ----------
@dataclass(frozen=True)
class CategoryTotal:
    group: str
    category: str
    kind: str                         # income | expense
    total: Decimal
    count: int


def by_category(s: Session, entity_id: int, first: date, last: date) -> list[CategoryTotal]:
    """Quanto entrou/saiu por categoria no período (competência: pago ou não). Maiores primeiro."""
    parent = aliased(Category)
    q = (select(Entry.kind, Entry.base_amount, Category.name, parent.name)
         .select_from(Entry).outerjoin(Category, Entry.category_id == Category.id)
         .outerjoin(parent, Category.parent_id == parent.id)
         .where(Entry.entity_id == entity_id, Entry.kind != "transfer", Entry.status != "canceled",
                Entry.competence_date.between(first, last)))
    acc: dict[tuple, list] = {}
    for kind, amount, cat, grp in s.execute(q):
        group = grp or cat or "Sem categoria"
        name = cat if grp else (cat or "Sem categoria")
        item = acc.setdefault((kind, group, name), [ZERO, 0])
        item[0] += Decimal(amount)
        item[1] += 1
    out = [CategoryTotal(g, c, k, v[0].quantize(CENT), v[1]) for (k, g, c), v in acc.items()]
    return sorted(out, key=lambda x: (x.kind != "income", -x.total))


# ---------- por contato ----------
@dataclass(frozen=True)
class ContactTotal:
    contact: str
    received: Decimal                  # o que esse contato te pagou
    paid: Decimal                      # o que você pagou a ele
    count: int


def by_contact(s: Session, entity_id: int, first: date, last: date) -> list[ContactTotal]:
    from finora.models import Contact
    q = (select(Contact.name, Entry.kind, Entry.base_amount)
         .select_from(Entry).join(Contact, Entry.contact_id == Contact.id)
         .where(Entry.entity_id == entity_id, Entry.kind != "transfer", Entry.status != "canceled",
                Entry.competence_date.between(first, last)))
    acc: dict[str, list] = {}
    for name, kind, amount in s.execute(q):
        item = acc.setdefault(name, [ZERO, ZERO, 0])
        item[0 if kind == "income" else 1] += Decimal(amount)
        item[2] += 1
    out = [ContactTotal(n, v[0].quantize(CENT), v[1].quantize(CENT), v[2]) for n, v in acc.items()]
    return sorted(out, key=lambda x: -(x.received + x.paid))


# ---------- por centro de custo ----------
@dataclass(frozen=True)
class CostCenterTotal:
    name: str
    budget: Decimal | None             # orçamento do período (mensal x nº de meses)
    spent: Decimal
    received: Decimal
    count: int


def by_cost_center(s: Session, entity_id: int, first: date, last: date) -> list[CostCenterTotal]:
    """Gastos e receitas de cada centro de custo no período (competência). Lançamentos sem centro entram
    numa linha "Sem centro de custo" no fim, para o total bater."""
    from finora.models import CostCenter
    q = (select(Entry.cost_center_id, Entry.kind, Entry.base_amount)
         .where(Entry.entity_id == entity_id, Entry.kind != "transfer", Entry.status != "canceled",
                Entry.competence_date.between(first, last)))
    acc: dict[int | None, list] = {}
    for cc, kind, amount in s.execute(q):
        item = acc.setdefault(cc, [ZERO, ZERO, 0])
        item[0 if kind == "expense" else 1] += Decimal(amount)
        item[2] += 1
    months = (last.year - first.year) * 12 + last.month - first.month + 1
    out = []
    for c in s.scalars(select(CostCenter).where(CostCenter.entity_id == entity_id)):
        spent, received, n = acc.pop(c.id, [ZERO, ZERO, 0])
        if n or c.is_active:
            budget = (Decimal(c.budget) * months).quantize(CENT) if c.budget else None
            out.append(CostCenterTotal(c.name, budget, spent.quantize(CENT), received.quantize(CENT), n))
    out.sort(key=lambda x: (-x.spent, x.name.lower()))
    if None in acc:
        spent, received, n = acc[None]
        out.append(CostCenterTotal("Sem centro de custo", None, spent.quantize(CENT), received.quantize(CENT), n))
    return out


# ---------- analítico ----------
def analytical(s: Session, entity_id: int, first: date, last: date, kind: str = "all") -> list:
    """Todas as receitas e despesas do período (competência), na ordem das datas. kind: all | income | expense."""
    q = entries.query(entity_id).where(Entry.kind != "transfer", Entry.competence_date.between(first, last))
    if kind in ("income", "expense"):
        q = q.where(Entry.kind == kind)
    return [entries.to_view(r) for r in s.execute(q.order_by(Entry.competence_date, Entry.id))]


# ---------- inadimplência (atrasados) ----------
AGING = [(30, "Até 30 dias"), (60, "31 a 60 dias"), (90, "61 a 90 dias"), (None, "Mais de 90 dias")]


@dataclass(frozen=True)
class OverdueItem:
    entry_id: int | None               # None = fatura de cartão
    kind: str                          # income | expense
    description: str
    contact: str
    due: date
    amount: Decimal
    days: int
    card_account_id: int | None = None


@dataclass(frozen=True)
class OverdueReport:
    payables: list[OverdueItem]        # você deve
    receivables: list[OverdueItem]     # te devem

    @staticmethod
    def buckets(items: list[OverdueItem]) -> list[tuple[str, Decimal, int]]:
        out = []
        lo = 0
        for hi, label in AGING:
            sel = [i for i in items if i.days > lo and (hi is None or i.days <= hi)]
            out.append((label, sum((i.amount for i in sel), ZERO), len(sel)))
            lo = hi or lo
        return out


def overdue(s: Session, entity_id: int, today: date | None = None) -> OverdueReport:
    """Tudo o que venceu e não foi pago/recebido, com os dias de atraso. Faturas de cartão atrasadas entram."""
    from finora.services import cards
    today = today or date.today()
    q = entries.query(entity_id).where(Entry.status == "pending", Entry.kind != "transfer", Entry.due_date < today)
    pay, rec = [], []
    for row in s.execute(q.order_by(Entry.due_date)):
        e = entries.to_view(row)
        item = OverdueItem(e.id, e.kind, e.description, e.contact or "", e.due_date, e.base_amount,
                           (today - e.due_date).days)
        (rec if e.kind == "income" else pay).append(item)
    for st in cards.open_statements(s, entity_id, today - timedelta(days=1), today):
        pay.append(OverdueItem(None, "expense", f"Fatura {st.account} {st.label}", "", st.due, st.remaining,
                               (today - st.due).days, st.account_id))
    pay.sort(key=lambda i: i.due)
    return OverdueReport(pay, rec)
