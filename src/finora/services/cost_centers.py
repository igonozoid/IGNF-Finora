"""Centros de custo: um segundo jeito de agrupar gastos, além da categoria — "Casa", "Carro", "Viagem",
"Filhos"… Cada um pode ter um orçamento mensal (quanto você pretende gastar nele por mês)."""
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
                                  spent, received, count, used.get(c.id, 0), bool(c.shared)))
    return out


def choices(s: Session, entity_id: int, keep_id: int | None = None) -> list[tuple[int, str]]:
    """Para o formulário do lançamento: os ativos (e o já escolhido, mesmo inativo)."""
    q = select(CostCenter.id, CostCenter.name, CostCenter.is_active).where(scope.cost_centers(entity_id))
    return [(i, n) for i, n, active in s.execute(q.order_by(func.lower(CostCenter.name))) if active or i == keep_id]


def _check(s: Session, entity_id: int, name: str, budget: Decimal | None, exclude_id: int | None = None):
    name = (name or "").strip()
    if not name:
        raise ValueError("Digite o nome do centro de custo.")
    if budget is not None and budget < 0:
        raise ValueError("O orçamento não pode ser negativo.")
    q = select(CostCenter.id).where(scope.cost_centers(entity_id), func.lower(CostCenter.name) == name.lower())
    if exclude_id is not None:
        q = q.where(CostCenter.id != exclude_id)
    if s.scalar(q) is not None:
        raise ValueError(f"Já existe um centro de custo chamado \"{name}\".")
    return name, (budget or None)


def create(s: Session, entity_id: int, name: str, budget: Decimal | None = None, shared: bool = False) -> int:
    name, budget = _check(s, entity_id, name, budget)
    c = CostCenter(entity_id=entity_id, name=name, budget=budget, is_active=True, shared=bool(shared))
    s.add(c)
    s.commit()
    return c.id


def update(s: Session, cc_id: int, name: str, budget: Decimal | None, is_active: bool = True,
           shared: bool | None = None) -> None:
    c = s.get(CostCenter, cc_id)
    if shared is not None:
        c.shared = shared
    c.name, c.budget = _check(s, c.entity_id, name, budget, exclude_id=c.id)
    c.is_active = is_active
    s.commit()


def delete(s: Session, cc_id: int) -> None:
    """Só exclui se nenhum lançamento usa; senão, a saída é inativar."""
    used = s.scalar(select(func.count(Entry.id)).where(Entry.cost_center_id == cc_id))
    if used:
        raise ValueError(f"Esse centro de custo está em {used} {'lançamento' if used == 1 else 'lançamentos'}. "
                         "Para não perder o histórico, inative-o em vez de excluir.")
    s.delete(s.get(CostCenter, cc_id))
    s.commit()
