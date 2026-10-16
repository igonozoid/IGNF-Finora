"""Contas: cadastro, saldo, ativar/inativar, compartilhar entre entidades e limite da edição Free."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from finora.core.licensing import LimitError, allowed, current_edition  # noqa: F401 (LimitError: usado pelas telas)
from finora.core.money import CURRENCIES
from finora.models import Account, Entity, Entry

KINDS = {
    "bank": "Conta no banco",
    "cash": "Dinheiro (carteira)",
    "card": "Cartão de crédito",
    "investment": "Investimento",
}




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
    base_balance: Decimal | None = None   # saldo na moeda principal (cotação mais recente); None = mesma moeda
    rate_missing: bool = False            # outra moeda sem nenhuma cotação cadastrada (conta 1 para 1)
    shared: bool = False                  # compartilhada com todas as entidades
    owner: str | None = None              # entidade que criou, quando veio compartilhada de outra

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


def _currency(s: Session, entity_id: int, currency: str | None, kind: str = "bank") -> str:
    """Moeda da conta: a da entidade, ou outra só se a edição permitir multimoeda.
    Cartão de crédito fica sempre na moeda principal (a fatura vem nela, mesmo com compras no exterior)."""
    base = s.get(Entity, entity_id).currency
    currency = currency or base
    if currency not in CURRENCIES:
        raise ValueError(f"Moeda não suportada: {currency}")
    if kind == "card" and currency != base:
        raise ValueError(f"Cartão de crédito fica na moeda principal ({base}): a fatura vem nela, mesmo com "
                         "compras em outra moeda.")
    if currency != base and not multi_currency():
        raise LimitError("Contas em outra moeda fazem parte das edições Plus e Pro.")
    return currency


def _movements(s: Session, account_ids: list[int]) -> dict[int, Decimal]:
    """Soma dos lançamentos pagos por conta. `amount` é sempre positivo; o tipo define o sinal.

    Transferência: sai de `account_id` e entra em `dest_account_id`. Vale para lançamentos de qualquer entidade:
    numa conta compartilhada o saldo é um só (as outras contas só recebem lançamentos da própria entidade).
    """
    if not account_ids:
        return {}
    paid = Entry.status.in_(("paid", "card"))   # card: compra no cartão
    out: dict[int, Decimal] = {}
    signed = case((Entry.kind.in_(("income", "deposit")), Entry.amount), else_=-Entry.amount)   # entries.INFLOW
    for acc_id, total in s.execute(select(Entry.account_id, func.sum(signed))
                                   .where(paid, Entry.account_id.in_(account_ids)).group_by(Entry.account_id)):
        out[acc_id] = out.get(acc_id, Decimal(0)) + Decimal(total)
    dest = select(Entry.dest_account_id, func.sum(func.coalesce(Entry.dest_amount, Entry.amount))).where(
        paid, Entry.kind == "transfer", Entry.dest_account_id.in_(account_ids)).group_by(Entry.dest_account_id)
    for acc_id, total in s.execute(dest):
        out[acc_id] = out.get(acc_id, Decimal(0)) + Decimal(total)
    return out


def list_accounts(s: Session, entity_id: int, include_inactive: bool = False) -> list[AccountView]:
    """As contas da entidade e as compartilhadas pelas outras."""
    from finora.services import fx, scope
    q = select(Account).where(scope.accounts(entity_id))
    if not include_inactive:
        q = q.where(Account.is_active)
    rows = list(s.scalars(q.order_by(Account.is_active.desc(), Account.name)))
    mov = _movements(s, [a.id for a in rows])
    conv = fx.Converter(s, entity_id)
    today = date.today()
    out = []
    for a in rows:
        balance = Decimal(a.opening_balance) + mov.get(a.id, Decimal(0))
        base = None if a.currency == conv.base else conv.convert(balance, a.currency, today)
        owner = None if a.entity_id == entity_id else s.get(Entity, a.entity_id).name
        out.append(AccountView(a.id, a.name, a.kind, a.currency, Decimal(a.opening_balance), balance, a.is_active,
                               a.closing_day, a.due_day, None if a.credit_limit is None else Decimal(a.credit_limit),
                               base, base is not None and conv.missing(a.currency), bool(a.shared), owner))
    return out


def total_balance(accounts: list[AccountView]) -> Decimal:
    """Dinheiro que você tem: contas ativas SEM cartões de crédito. A dívida do cartão aparece
    como fatura a pagar (contar as duas coisas seria descontar a mesma dívida duas vezes)."""
    return sum((a.balance if a.base_balance is None else a.base_balance
                for a in accounts if a.is_active and a.kind != "card"), Decimal("0.00"))


def money_accounts(accounts: list[AccountView]) -> list[AccountView]:
    """Contas ativas que entram no saldo (sem cartões)."""
    return [a for a in accounts if a.is_active and a.kind != "card"]


def _check(s: Session, entity_id: int, name: str, kind: str, exclude_id: int | None = None,
           shared: bool = False) -> str:
    """Nome único entre as contas que a entidade enxerga; compartilhada, único em todas as entidades."""
    from finora.services import scope
    name = name.strip()
    if not name:
        raise ValueError("Dê um nome para a conta.")
    if kind not in KINDS:
        raise ValueError(f"Tipo de conta inválido: {kind}")
    if shared and kind == "card":
        raise ValueError("Cartão de crédito não pode ser compartilhado: a fatura é de uma entidade só.")
    q = select(Account.id).where(func.lower(Account.name) == name.lower())
    if not shared:
        q = q.where(scope.accounts(entity_id))
    if exclude_id is not None:
        q = q.where(Account.id != exclude_id)
    if s.scalar(q) is not None:
        where = " em outra entidade" if shared else ""
        raise ValueError(f"Já existe uma conta chamada \"{name}\"{where}.")
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
           credit_limit: Decimal | None = None, shared: bool = False) -> int:
    """Para cartão, `opening_balance` é a fatura em aberto (vira saldo negativo)."""
    name = _check(s, entity_id, name, kind, shared=shared)
    closing_day, due_day, credit_limit = _card_fields(kind, closing_day, due_day, credit_limit)
    if not can_add(s, entity_id):
        raise LimitError(f"A edição Free permite até {limit()} contas ativas.")
    currency = _currency(s, entity_id, currency, kind)
    if kind == "card":
        opening_balance = -abs(opening_balance)
    a = Account(entity_id=entity_id, name=name, kind=kind, currency=currency,
                opening_balance=opening_balance, is_active=True,
                closing_day=closing_day, due_day=due_day, credit_limit=credit_limit, shared=bool(shared))
    s.add(a)
    s.commit()
    return a.id


def update(s: Session, account_id: int, *, name: str, kind: str, opening_balance: Decimal,
           currency: str | None = None, closing_day: int | None = None, due_day: int | None = None,
           credit_limit: Decimal | None = None, shared: bool | None = None) -> None:
    """Mudar fechamento/vencimento vale para as compras NOVAS; as já lançadas ficam na fatura em que estão.
    `shared` None mantém como está. Deixar de compartilhar não pode se outra entidade já lançou nela."""
    a = s.get(Account, account_id)
    shared = a.shared if shared is None else bool(shared)
    if a.shared and not shared:
        others = s.scalar(select(func.count(Entry.id)).where(
            Entry.entity_id != a.entity_id, (Entry.account_id == a.id) | (Entry.dest_account_id == a.id)))
        if others:
            raise ValueError("Outras entidades já têm lançamentos nesta conta: ela precisa continuar "
                             "compartilhada (dá para inativar).")
    a.name = _check(s, a.entity_id, name, kind, exclude_id=a.id, shared=shared)
    a.shared = shared
    a.closing_day, a.due_day, a.credit_limit = _card_fields(kind, closing_day, due_day, credit_limit)
    if (currency and currency != a.currency) or (kind == "card" and a.kind != "card"):
        a.currency = _currency(s, a.entity_id, currency or a.currency, kind)
    changed_currency = a.currency
    a.kind = kind
    a.opening_balance = -abs(opening_balance) if kind == "card" else opening_balance
    s.commit()
    from finora.services import fx
    users = {a.entity_id} | set(s.scalars(select(Entry.entity_id).where(Entry.account_id == a.id).distinct()))
    for ent in sorted(users):                               # compartilhada: cada entidade na própria moeda principal
        fx.recompute(s, ent, changed_currency)              # lançamentos da conta: valor na moeda principal


def set_active(s: Session, account_id: int, active: bool) -> None:
    a = s.get(Account, account_id)
    if active and not a.is_active and not can_add(s, a.entity_id):
        raise LimitError(f"A edição Free permite até {limit()} contas ativas.")
    a.is_active = active
    s.commit()
