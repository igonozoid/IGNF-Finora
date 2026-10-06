"""Contas: cadastro, saldo, ativar/inativar e limite da edição Free."""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from finora.core.licensing import allowed, current_edition
from finora.core.money import CURRENCIES
from finora.models import Account, Entity, Entry

KINDS = {
    "bank": "Conta no banco",
    "cash": "Dinheiro (carteira)",
    "card": "Cartão de crédito",
    "investment": "Investimento",
}


class LimitError(Exception):
    """A edição atual não permite mais contas ativas."""


@dataclass(frozen=True)
class AccountView:
    id: int
    name: str
    kind: str
    currency: str
    opening_balance: Decimal
    balance: Decimal
    is_active: bool
    closing_day: int | None = None      # cartão: dia em que a fatura fecha
    due_day: int | None = None          # cartão: dia em que a fatura vence
    credit_limit: Decimal | None = None

    @property
    def kind_label(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def card_info(self) -> str:
        """Ex.: "Fecha dia 25 · vence dia 5"."""
        if self.kind != "card":
            return ""
        if not (self.closing_day and self.due_day):
            return "Sem fechamento e vencimento"
        return f"Fecha dia {self.closing_day} · vence dia {self.due_day}"


def limit() -> int | None:
    """Máximo de contas ativas na edição atual (None = ilimitado)."""
    return allowed(current_edition(), "accounts_max")


def active_count(s: Session, entity_id: int) -> int:
    return s.scalar(select(func.count(Account.id)).where(Account.entity_id == entity_id, Account.is_active)) or 0


def can_add(s: Session, entity_id: int) -> bool:
    lim = limit()
    return lim is None or active_count(s, entity_id) < lim


def multi_currency() -> bool:
    return bool(allowed(current_edition(), "multi_currency"))


def _currency(s: Session, entity_id: int, currency: str | None) -> str:
    """Moeda da conta: a da entidade, ou outra só se a edição permitir multimoeda."""
    base = s.get(Entity, entity_id).currency
    currency = currency or base
    if currency not in CURRENCIES:
        raise ValueError(f"Moeda não suportada: {currency}")
    if currency != base and not multi_currency():
        raise LimitError("Contas em outra moeda fazem parte das edições Plus e Pro.")
    return currency


def _movements(s: Session, entity_id: int) -> dict[int, Decimal]:
    """Soma dos lançamentos pagos por conta. `amount` é sempre positivo; o tipo define o sinal.

    Transferência: sai de `account_id` e entra em `dest_account_id`.
    """
    paid = (Entry.entity_id == entity_id) & (Entry.status.in_(("paid", "card")))   # card: compra no cartão
    out: dict[int, Decimal] = {}
    signed = case((Entry.kind == "income", Entry.amount), else_=-Entry.amount)
    for acc_id, total in s.execute(select(Entry.account_id, func.sum(signed)).where(paid).group_by(Entry.account_id)):
        out[acc_id] = out.get(acc_id, Decimal(0)) + Decimal(total)
    dest = select(Entry.dest_account_id, func.sum(Entry.amount)).where(
        paid, Entry.kind == "transfer", Entry.dest_account_id.is_not(None)).group_by(Entry.dest_account_id)
    for acc_id, total in s.execute(dest):
        out[acc_id] = out.get(acc_id, Decimal(0)) + Decimal(total)
    return out


def list_accounts(s: Session, entity_id: int, include_inactive: bool = False) -> list[AccountView]:
    q = select(Account).where(Account.entity_id == entity_id)
    if not include_inactive:
        q = q.where(Account.is_active)
    q = q.order_by(Account.is_active.desc(), Account.name)
    mov = _movements(s, entity_id)
    return [
        AccountView(a.id, a.name, a.kind, a.currency, Decimal(a.opening_balance),
                    Decimal(a.opening_balance) + mov.get(a.id, Decimal(0)), a.is_active,
                    a.closing_day, a.due_day, None if a.credit_limit is None else Decimal(a.credit_limit))
        for a in s.scalars(q)
    ]


def total_balance(accounts: list[AccountView]) -> Decimal:
    """Dinheiro que você tem: contas ativas SEM cartões de crédito. A dívida do cartão aparece
    como fatura a pagar (contar as duas coisas seria descontar a mesma dívida duas vezes)."""
    return sum((a.balance for a in accounts if a.is_active and a.kind != "card"), Decimal("0.00"))


def money_accounts(accounts: list[AccountView]) -> list[AccountView]:
    """Contas ativas que entram no saldo (sem cartões)."""
    return [a for a in accounts if a.is_active and a.kind != "card"]


def _check(s: Session, entity_id: int, name: str, kind: str, exclude_id: int | None = None) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Dê um nome para a conta.")
    if kind not in KINDS:
        raise ValueError(f"Tipo de conta inválido: {kind}")
    q = select(Account.id).where(Account.entity_id == entity_id, func.lower(Account.name) == name.lower())
    if exclude_id is not None:
        q = q.where(Account.id != exclude_id)
    if s.scalar(q) is not None:
        raise ValueError(f"Já existe uma conta chamada \"{name}\".")
    return name


def _card_fields(kind: str, closing_day, due_day, credit_limit) -> tuple:
    """Fechamento/vencimento/limite só existem para cartão. Dias de 1 a 31 (meses curtos usam o último dia)."""
    if kind != "card":
        return None, None, None
    if (closing_day is None) != (due_day is None):
        raise ValueError("Informe o dia de fechamento e o dia de vencimento da fatura.")
    for d in (closing_day, due_day):
        if d is not None and not 1 <= d <= 31:
            raise ValueError("Os dias de fechamento e vencimento vão de 1 a 31.")
    if closing_day is not None and closing_day == due_day:
        raise ValueError("O vencimento precisa ser num dia diferente do fechamento.")
    if credit_limit is not None and credit_limit < 0:
        raise ValueError("O limite não pode ser negativo.")
    return closing_day, due_day, credit_limit


def create(s: Session, entity_id: int, *, name: str, kind: str, opening_balance: Decimal,
           currency: str | None = None, closing_day: int | None = None, due_day: int | None = None,
           credit_limit: Decimal | None = None) -> int:
    """Para cartão, `opening_balance` é a fatura em aberto (vira saldo negativo)."""
    name = _check(s, entity_id, name, kind)
    closing_day, due_day, credit_limit = _card_fields(kind, closing_day, due_day, credit_limit)
    if not can_add(s, entity_id):
        raise LimitError(f"A edição Free permite até {limit()} contas ativas.")
    currency = _currency(s, entity_id, currency)
    if kind == "card":
        opening_balance = -abs(opening_balance)
    a = Account(entity_id=entity_id, name=name, kind=kind, currency=currency,
                opening_balance=opening_balance, is_active=True,
                closing_day=closing_day, due_day=due_day, credit_limit=credit_limit)
    s.add(a)
    s.commit()
    return a.id


def update(s: Session, account_id: int, *, name: str, kind: str, opening_balance: Decimal,
           currency: str | None = None, closing_day: int | None = None, due_day: int | None = None,
           credit_limit: Decimal | None = None) -> None:
    """Mudar fechamento/vencimento vale para as compras NOVAS; as já lançadas ficam na fatura em que estão."""
    a = s.get(Account, account_id)
    a.name = _check(s, a.entity_id, name, kind, exclude_id=a.id)
    a.closing_day, a.due_day, a.credit_limit = _card_fields(kind, closing_day, due_day, credit_limit)
    if currency and currency != a.currency:
        a.currency = _currency(s, a.entity_id, currency)
    a.kind = kind
    a.opening_balance = -abs(opening_balance) if kind == "card" else opening_balance
    s.commit()


def set_active(s: Session, account_id: int, active: bool) -> None:
    a = s.get(Account, account_id)
    if active and not a.is_active and not can_add(s, a.entity_id):
        raise LimitError(f"A edição Free permite até {limit()} contas ativas.")
    a.is_active = active
    s.commit()
