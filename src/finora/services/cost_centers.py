"""Centros de custo: um segundo jeito de agrupar gastos, além da categoria — "Casa", "Carro", "Viagem",
"Filhos"… Cada um pode ter um orçamento mensal (quanto você pretende gastar nele por mês).

Como no MCC, cada centro diz se vale para despesas (centro de custo), receitas (centro de lucro) ou os dois, e pode
ter uma projeção mensal de receita. O lançamento só aceita um centro que valha para o tipo dele."""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.models import CostCenter, Entry
from finora.services import scope
from finora.services.entries import month_range

ZERO = Decimal(0)


@dataclass(frozen=True)
class CostCenterView:
    id: int
    name: str
    budget: Decimal | None       # orçamento mensal (None = sem orçamento)
    is_active: bool
    spent: Decimal               # despesas do mês (competência)
    received: Decimal            # receitas do mês ligadas a ele
    count: int                   # lançamentos no mês
    used: int                    # lançamentos no total (não deixa excluir)
    shared: bool = False         # compartilhado com todas as entidades
    applies_expense: bool = True
    applies_income: bool = True
    projection: Decimal | None = None   # projeção mensal de receita

    @property
    def applies_label(self) -> str:
        return ("Despesas e receitas" if self.applies_expense and self.applies_income
                else "Só despesas" if self.applies_expense else "Só receitas")

    @property
    def income_share(self) -> Decimal | None:
        """Quanto da projeção de receita já entrou (1 = 100%). None sem projeção."""
        return self.received / self.projection if self.projection else None

    @property
    def share(self) -> Decimal | None:
        """Quanto do orçamento já foi gasto (1 = 100%). None sem orçamento."""
        if not self.budget:
            return None
        return self.spent / self.budget

    @property
    def status(self) -> str:
        """'none' sem orçamento · 'ok' · 'warn' (80% ou mais) · 'over' (estourou)."""
        share = self.share
        if share is None:
            return "none"
        return "over" if share > 1 else "warn" if share >= Decimal("0.8") else "ok"


def _sums(s: Session, entity_id: int, year: int, month: int) -> dict[int, tuple[Decimal, Decimal, int]]:
    first, last = month_range(year, month)
    rows = s.execute(
        select(Entry.cost_center_id, Entry.kind, func.sum(Entry.base_amount), func.count(Entry.id))
        .where(Entry.entity_id == entity_id, Entry.cost_center_id.is_not(None), Entry.status != "canceled",
               Entry.kind.in_(("income", "expense")), Entry.competence_date.between(first, last))
        .group_by(Entry.cost_center_id, Entry.kind))
    out: dict[int, list] = {}
    for cc, kind, total, n in rows:
        spent, received, count = out.get(cc, [ZERO, ZERO, 0])
        total = Decimal(total or 0)
        out[cc] = [spent + total, received, count + n] if kind == "expense" else [spent, received + total, count + n]
    return {k: tuple(v) for k, v in out.items()}


def list_centers(s: Session, entity_id: int, year: int, month: int,
                 include_inactive: bool = True) -> list[CostCenterView]:
    sums = _sums(s, entity_id, year, month)
    used = dict(s.execute(select(Entry.cost_center_id, func.count(Entry.id))
                          .where(Entry.entity_id == entity_id, Entry.cost_center_id.is_not(None))
                          .group_by(Entry.cost_center_id)).all())
    q = select(CostCenter).where(scope.cost_centers(entity_id))
    if not include_inactive:
        q = q.where(CostCenter.is_active)
    out = []
    for c in s.scalars(q.order_by(CostCenter.is_active.desc(), func.lower(CostCenter.name))):
        spent, received, count = sums.get(c.id, (ZERO, ZERO, 0))
        out.append(CostCenterView(c.id, c.name, Decimal(c.budget) if c.budget is not None else None, c.is_active,
                                  spent, received, count, used.get(c.id, 0), bool(c.shared),
                                  bool(c.applies_expense), bool(c.applies_income),
                                  Decimal(c.projection) if c.projection is not None else None))
    return out


def choices(s: Session, entity_id: int, keep_id: int | None = None, kind: str | None = None) -> list[tuple[int, str]]:
    """Para o formulário do lançamento: os ativos que valem para o tipo `kind` (expense/income; None = todos),
    e o já escolhido, mesmo inativo."""
    q = select(CostCenter).where(scope.cost_centers(entity_id)).order_by(func.lower(CostCenter.name))
    return [(c.id, c.name) for c in s.scalars(q)
            if c.id == keep_id or (c.is_active and applies(c, kind))]


def applies(c: CostCenter, kind: str | None) -> bool:
    """O centro vale para esse tipo de lançamento?"""
    if kind == "expense":
        return bool(c.applies_expense)
    if kind == "income":
        return bool(c.applies_income)
    return True


def _check(s: Session, entity_id: int, name: str, budget: Decimal | None, exclude_id: int | None = None,
           applies_expense: bool = True, applies_income: bool = True, projection: Decimal | None = None):
    name = (name or "").strip()
    if not name:
        raise ValueError("Digite o nome do centro de custo.")
    if budget is not None and budget < 0:
        raise ValueError("O orçamento não pode ser negativo.")
    if projection is not None and projection < 0:
        raise ValueError("A projeção não pode ser negativa.")
    if not (applies_expense or applies_income):
        raise ValueError("Marque se o centro vale para despesas, para receitas ou para os dois.")
    q = select(CostCenter.id).where(scope.cost_centers(entity_id), func.lower(CostCenter.name) == name.lower())
    if exclude_id is not None:
        q = q.where(CostCenter.id != exclude_id)
    if s.scalar(q) is not None:
        raise ValueError(f"Já existe um centro de custo chamado \"{name}\".")
    return name, (budget or None)


def create(s: Session, entity_id: int, name: str, budget: Decimal | None = None, shared: bool = False, *,
           applies_expense: bool = True, applies_income: bool = True, projection: Decimal | None = None) -> int:
    name, budget = _check(s, entity_id, name, budget, None, applies_expense, applies_income, projection)
    c = CostCenter(entity_id=entity_id, name=name, budget=budget if applies_expense else None, is_active=True,
                   shared=bool(shared), applies_expense=bool(applies_expense), applies_income=bool(applies_income),
                   projection=(projection or None) if applies_income else None)
    s.add(c)
    s.commit()
    return c.id


_KEEP = object()


def update(s: Session, cc_id: int, name: str, budget: Decimal | None, is_active: bool = True,
           shared: bool | None = None, *, applies_expense: bool | None = None, applies_income: bool | None = None,
           projection=_KEEP) -> None:
    """`applies_*` None e `projection` omitido mantêm como estão."""
    c = s.get(CostCenter, cc_id)
    if shared is not None:
        c.shared = shared
    exp = c.applies_expense if applies_expense is None else bool(applies_expense)
    inc = c.applies_income if applies_income is None else bool(applies_income)
    proj = c.projection if projection is _KEEP else projection
    c.name, budget = _check(s, c.entity_id, name, budget, c.id, exp, inc, proj)
    c.budget = budget if exp else None
    c.applies_expense, c.applies_income = exp, inc
    c.projection = (proj or None) if inc else None
    c.is_active = is_active
    s.commit()


def delete(s: Session, cc_id: int) -> None:
    """Só exclui se nenhum lançamento usa; senão, a saída é inativar."""
    used = s.scalar(select(func.count(Entry.id)).where(Entry.cost_center_id == cc_id)
                    .execution_options(include_deleted=True))       # os da lixeira podem voltar
    if used:
        raise ValueError(f"Esse centro de custo está em {used} {'lançamento' if used == 1 else 'lançamentos'} "
                         "(contando os da lixeira). "
                         "Para não perder o histórico, inative-o em vez de excluir.")
    s.delete(s.get(CostCenter, cc_id))
    s.commit()
