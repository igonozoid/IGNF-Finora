"""Orçado x realizado: orçamento mensal por categoria de despesa e quanto já foi gasto.

O orçamento pode ficar no grupo (ex.: Alimentação) ou nas subcategorias (Supermercado, Restaurante…).
Grupo sem orçamento próprio usa a soma das subcategorias. Gasto = despesas pela data de competência
(a data da compra no cartão, o vencimento nas demais), pagas ou não — como na DRE.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core import money
from finora.models import Budget, Category, Entry
from finora.services import categories
from finora.services.entries import month_range
from finora.services.receipts import MONTHS as MONTHS_PT

ZERO = Decimal(0)
WARN = Decimal("0.8")


@dataclass(frozen=True)
class BudgetRow:
    category_id: int
    name: str
    level: int                   # 0 = grupo, 1 = subcategoria
    own: Decimal | None          # orçamento mensal gravado nesta categoria
    monthly: Decimal | None      # orçamento mensal que vale (grupo sem o seu = soma das subcategorias)
    planned: Decimal | None      # orçamento do período (mensal x nº de meses)
    actual: Decimal              # gasto no período

    @property
    def share(self) -> Decimal | None:
        return self.actual / self.planned if self.planned else None

    @property
    def status(self) -> str:
        """'none' sem orçamento · 'ok' · 'warn' (80% ou mais) · 'over' (estourou)."""
        share = self.share
        if share is None:
            return "none"
        return "over" if share > 1 else "warn" if share >= WARN else "ok"

    @property
    def left(self) -> Decimal | None:
        """Quanto ainda dá para gastar (negativo = passou)."""
        return None if self.planned is None else self.planned - self.actual


def _months(first: date, last: date) -> int:
    return (last.year - first.year) * 12 + last.month - first.month + 1


def _own(s: Session, entity_id: int) -> dict[int, Decimal]:
    return {cid: Decimal(v) for cid, v in s.execute(select(Budget.category_id, Budget.amount)
                                                    .where(Budget.entity_id == entity_id))}


def _spent(s: Session, entity_id: int, first: date, last: date) -> dict[int, Decimal]:
    rows = s.execute(select(Entry.category_id, func.sum(Entry.amount))
                     .where(Entry.entity_id == entity_id, Entry.kind == "expense", Entry.status != "canceled",
                            Entry.category_id.is_not(None), Entry.competence_date.between(first, last))
                     .group_by(Entry.category_id))
    return {cid: Decimal(v or 0) for cid, v in rows}


def report(s: Session, entity_id: int, first: date, last: date, only_used: bool = False) -> list[BudgetRow]:
    """Linhas na ordem da DRE: grupo e, abaixo, as subcategorias. `only_used`: só o que tem orçamento ou gasto."""
    own, spent, n = _own(s, entity_id), _spent(s, entity_id, first, last), _months(first, last)
    out = []
    for g in categories.tree(s, entity_id):
        if g.kind != "expense":
            continue
        kids = []
        for c in g.children:
            mine = own.get(c.id)
            kids.append(BudgetRow(c.id, c.name, 1, mine, mine, mine * n if mine else None, spent.get(c.id, ZERO)))
        kid_budget = sum((k.own for k in kids if k.own), ZERO)
        monthly = own.get(g.id) or (kid_budget or None)
        actual = spent.get(g.id, ZERO) + sum((k.actual for k in kids), ZERO)
        group = BudgetRow(g.id, g.name, 0, own.get(g.id), monthly, monthly * n if monthly else None, actual)
        if only_used:
            kids = [k for k in kids if k.own or k.actual]
            if not (group.monthly or group.actual):
                continue
        out.append(group)
        out.extend(kids)
    return out


def set_budget(s: Session, entity_id: int, category_id: int, amount: Decimal | None) -> None:
    """Grava o orçamento mensal da categoria. Vazio ou zero apaga."""
    cat = s.get(Category, category_id)
    if cat is None or cat.entity_id != entity_id:
        raise ValueError("Categoria inválida.")
    if cat.kind != "expense":
        raise ValueError("Orçamento é só para categorias de despesa.")
    if amount is not None and amount < 0:
        raise ValueError("O orçamento não pode ser negativo.")
    b = s.scalar(select(Budget).where(Budget.entity_id == entity_id, Budget.category_id == category_id))
    if not amount:
        if b is not None:
            s.delete(b)
    elif b is None:
        s.add(Budget(entity_id=entity_id, category_id=category_id, amount=amount))
    else:
        b.amount = amount
    s.commit()


def overspent(s: Session, entity_id: int, category_id: int | None, when: date, currency: str = "BRL") -> str | None:
    """Depois de lançar uma despesa: se a categoria (ou o grupo dela) passou do orçamento do mês, o aviso."""
    if category_id is None:
        return None
    cat = s.get(Category, category_id)
    if cat is None or cat.kind != "expense":
        return None
    first, last = month_range(when.year, when.month)
    rows = {r.category_id: r for r in report(s, entity_id, first, last)}
    for cid in (category_id, cat.parent_id):          # a própria categoria primeiro, depois o grupo
        row = rows.get(cid)
        if row is not None and row.status == "over":
            return (f"Atenção: {row.name} passou do orçamento de {MONTHS_PT[when.month - 1]} — gasto "
                    f"{money.fmt(row.actual, currency)} de {money.fmt(row.planned, currency)}.")
    return None
