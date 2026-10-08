"""Metas e objetivos: reserva de emergência, viagem, carro… com quanto já tem e quanto falta.

O progresso vem do saldo de uma conta (ex.: a poupança da reserva) ou de um valor guardado que a pessoa vai
somando ("Guardei mais R$ 200"). Com data, mostra quanto guardar por mês para chegar lá.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core.money import CENT
from finora.models import Account, Goal

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class GoalView:
    id: int
    name: str
    target: Decimal
    current: Decimal              # saldo da conta (moeda principal) ou o valor guardado
    due_date: date | None
    account_id: int | None
    account: str | None
    saved: Decimal
    is_active: bool

    @property
    def pct(self) -> int:
        if self.target <= 0:
            return 0
        return max(0, min(100, int(self.current * 100 / self.target)))

    @property
    def missing(self) -> Decimal:
        return max(ZERO, self.target - self.current)

    @property
    def done(self) -> bool:
        return self.current >= self.target > 0

    def months_left(self, today: date | None = None) -> int | None:
        if self.due_date is None:
            return None
        today = today or date.today()
        return max(0, (self.due_date.year - today.year) * 12 + self.due_date.month - today.month)

    def monthly(self, today: date | None = None) -> Decimal | None:
        """Quanto guardar por mês até a data (no mês da data conta como último)."""
        n = self.months_left(today)
        if n is None or self.done:
            return None
        return (self.missing / max(1, n)).quantize(CENT, rounding=ROUND_UP)


def _current(s: Session, g: Goal, conv) -> Decimal:
    if g.account_id is None:
        return Decimal(g.saved or 0)
    from finora.services import accounts
    acc = next((a for a in accounts.list_accounts(s, g.entity_id, include_inactive=True) if a.id == g.account_id),
               None)
    if acc is None:
        return Decimal(g.saved or 0)
    return acc.base_balance if acc.base_balance is not None else acc.balance


def list_goals(s: Session, entity_id: int, include_inactive: bool = False) -> list[GoalView]:
    q = (select(Goal, Account.name).outerjoin(Account, Account.id == Goal.account_id)
         .where(Goal.entity_id == entity_id))
    if not include_inactive:
        q = q.where(Goal.is_active.is_(True))
    out = []
    for g, acc in s.execute(q.order_by(Goal.is_active.desc(), Goal.due_date.is_(None), Goal.due_date,
                                       func.lower(Goal.name))):
        out.append(GoalView(g.id, g.name, Decimal(g.target), _current(s, g, None), g.due_date, g.account_id, acc,
                            Decimal(g.saved or 0), g.is_active))
    return out


def _check(s: Session, entity_id: int, name: str, target: Decimal, account_id: int | None,
           exclude_id: int | None = None) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("Dê um nome para a meta (ex.: Reserva de emergência).")
    if len(name) > 80:
        raise ValueError("Nome longo demais (até 80 letras).")
    if target is None or target <= 0:
        raise ValueError("Informe quanto quer juntar.")
    if account_id is not None:
        acc = s.get(Account, account_id)
        if acc is None or acc.entity_id != entity_id or acc.kind == "card":
            raise ValueError("Escolha uma conta desta entidade (cartão não serve).")
    dup = s.scalar(select(Goal.id).where(Goal.entity_id == entity_id, func.lower(Goal.name) == name.lower(),
                                         Goal.id != (exclude_id or 0)))
    if dup:
        raise ValueError("Já existe uma meta com esse nome.")
    return name


def create(s: Session, entity_id: int, *, name: str, target: Decimal, due_date: date | None = None,
           account_id: int | None = None, saved: Decimal = ZERO) -> int:
    name = _check(s, entity_id, name, target, account_id)
    g = Goal(entity_id=entity_id, name=name, target=Decimal(target).quantize(CENT), due_date=due_date,
             account_id=account_id, saved=Decimal(saved or 0).quantize(CENT), is_active=True)
    s.add(g)
    s.commit()
    return g.id


def update(s: Session, goal_id: int, *, name: str, target: Decimal, due_date: date | None = None,
           account_id: int | None = None, saved: Decimal | None = None, is_active: bool = True) -> None:
    g = s.get(Goal, goal_id)
    g.name = _check(s, g.entity_id, name, target, account_id, exclude_id=goal_id)
    g.target, g.due_date, g.account_id, g.is_active = Decimal(target).quantize(CENT), due_date, account_id, is_active
    if saved is not None:
        g.saved = Decimal(saved).quantize(CENT)
    s.commit()


def add_saving(s: Session, goal_id: int, amount: Decimal) -> Decimal:
    """'Guardei mais R$ 200' (ou tirei, com valor negativo). Só para meta sem conta ligada."""
    g = s.get(Goal, goal_id)
    if g.account_id is not None:
        raise ValueError("Essa meta acompanha o saldo da conta: o valor muda sozinho quando você lança nela.")
    new = Decimal(g.saved or 0) + Decimal(amount)
    if new < 0:
        raise ValueError("O valor guardado não pode ficar negativo.")
    g.saved = new.quantize(CENT)
    s.commit()
    return g.saved


def delete(s: Session, goal_id: int) -> None:
    s.delete(s.get(Goal, goal_id))
    s.commit()
