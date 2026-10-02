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
from sqlalchemy.orm import Session

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
    n = {"3m": 3, "6m": 6, "12m": 12}[key]
    return [(d.year, d.month) for d in (entries.add_months(first, -i) for i in range(n - 1, -1, -1))]


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
    q = (select(when, Entry.kind, Entry.amount, Category.dre_group, Category.name)
         .select_from(Entry).outerjoin(Category, Entry.category_id == Category.id)
         .where(Entry.entity_id == entity_id, Entry.kind != "transfer", when.between(first, last)))
    q = q.where(Entry.status == "paid") if regime == "cash" else q.where(Entry.status != "canceled")
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
    q = (select(Entry.due_date, Entry.kind, Entry.amount, Entry.description)
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

    out, bal = [], start
    for i in range(days):
        d = today + timedelta(days=i)
        moves = by_day.get(d, [])
        inc = sum((a for k, a, _ in moves if k == "income"), ZERO)
        exp = sum((a for k, a, _ in moves if k == "expense"), ZERO)
        bal = bal + inc - exp
        out.append(FlowDay(d, inc.quantize(CENT), exp.quantize(CENT), bal.quantize(CENT), [m[2] for m in moves]))
    return CashFlow(start.quantize(CENT), out, overdue)
