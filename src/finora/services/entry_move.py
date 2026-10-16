"""Levar lançamentos para outra entidade (no MCC: "transferir para outra conta controle").

O lançamento troca de entidade e de conta (a conta escolhida, da entidade de destino, na mesma moeda). Categoria e
contato que a entidade de destino não enxerga são trocados pelos de mesmo nome lá (o contato é criado se faltar);
categoria sem par e centro de custo não compartilhado ficam em branco. Anexos vão junto; a conciliação da conta de
origem solta as linhas de extrato ligadas a eles. Lançamentos de uma mesma série seguem juntos numa série nova.

Ficam de fora: transferências entre contas, compras no cartão e os gerados por Estoque, Vendas ou Pecuária (esses se
mudam pelo próprio módulo). Precisa de acesso Total ao Financeiro no destino e de período aberto nas duas entidades.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from finora.core.current import current
from finora.models import (
    Account, Attachment, BankLine, Category, Contact, CostCenter, Entity, Entry, HerdEvent, Sale, StockMove,
)
from finora.services import cards, period_lock, permissions, scope


@dataclass(frozen=True)
class MoveResult:
    moved: int
    categories_cleared: int       # categoria sem par na entidade de destino
    cost_centers_cleared: int


def destinations(s: Session, origin_id: int) -> list[tuple[int, str, list[tuple[int, str]]]]:
    """Entidades para onde o usuário pode levar lançamentos: (id, nome, [(conta, nome da conta)]).
    Só as ativas, com acesso Total ao Financeiro e com alguma conta ativa que não seja cartão."""
    out = []
    for ent in s.scalars(select(Entity).where(Entity.is_active, Entity.id != origin_id).order_by(func.lower(Entity.name))):
        if not permissions.at_least(permissions.level(s, current.user_id, ent.id, "financial"), "full"):
            continue
        accs = [(a.id, a.name) for a in s.scalars(select(Account).where(Account.entity_id == ent.id, Account.is_active)
                                                  .order_by(Account.id)) if not cards.is_configured(a)]
        if accs:
            out.append((ent.id, ent.name, accs))
    return out


def _check(s: Session, e: Entry, acc: Account) -> None:
    name = f"\"{e.description}\""
    if e.kind == "transfer":
        raise ValueError(f"{name} é transferência entre contas: não dá para levar para outra entidade.")
    if e.status == cards.CARD_STATUS:
        raise ValueError(f"{name} é compra no cartão: ela fica na fatura do cartão.")
    if s.get(Account, e.account_id).currency != acc.currency:
        raise ValueError(f"{name} está em outra moeda que a conta {acc.name}.")
    linked = (s.scalar(select(StockMove.id).where(StockMove.entry_id == e.id).limit(1))
              or s.scalar(select(HerdEvent.id).where(HerdEvent.entry_id == e.id).limit(1))
              or (e.series_id and s.scalar(select(Sale.id).where(Sale.series_id == e.series_id).limit(1))))
    if linked:
        raise ValueError(f"{name} foi gerado por Estoque, Vendas ou Pecuária: mude por lá.")


def _contact_in(s: Session, c: Contact, entity_id: int) -> int:
    same = s.scalars(select(Contact).where(scope.contacts(entity_id), func.lower(Contact.name) == c.name.lower())
                     .order_by((Contact.entity_id == entity_id).desc())).first()
    if same is None:
        same = Contact(entity_id=entity_id, person_type=c.person_type, document=c.document, name=c.name,
                       is_customer=c.is_customer, is_supplier=c.is_supplier, is_employee=c.is_employee)
        s.add(same)
        s.flush()
    return same.id


def _category_in(s: Session, cat: Category, entity_id: int) -> int | None:
    return s.scalar(select(Category.id).where(scope.categories(entity_id), Category.kind == cat.kind,
                                              Category.is_active.is_(True),
                                              func.lower(Category.name) == cat.name.lower())
                    .order_by(Category.code).limit(1))


def move_to_entity(s: Session, entry_ids: list[int], dest_entity_id: int, account_id: int) -> MoveResult:
    rows = [s.get(Entry, i) for i in entry_ids]
    if not rows or any(e is None for e in rows):
        raise ValueError("Escolha os lançamentos.")
    origin = rows[0].entity_id
    if any(e.entity_id != origin for e in rows):
        raise ValueError("Os lançamentos precisam ser da mesma entidade.")
    dest = s.get(Entity, dest_entity_id)
    if dest is None or dest.id == origin or not dest.is_active:
        raise ValueError("Escolha outra entidade, ativa.")
    if not permissions.at_least(permissions.level(s, current.user_id, dest.id, "financial"), "full"):
        raise permissions.AccessDenied(f"Você não tem acesso Total ao Financeiro em {dest.name}.")
    acc = s.get(Account, account_id) if account_id else None
    if acc is None or acc.entity_id != dest.id or not acc.is_active:
        raise ValueError(f"Escolha uma conta ativa de {dest.name}.")
    if cards.is_configured(acc):
        raise ValueError("Escolha uma conta que não seja cartão de crédito.")
    for e in rows:
        _check(s, e, acc)
        for ent in (origin, dest.id):
            if period_lock.is_locked(s, ent, e.competence_date):
                lock = period_lock.locked_through(s, ent)
                raise period_lock.PeriodLockedError(
                    f"\"{e.description}\" é de {e.competence_date:%d/%m/%Y} e o período até {lock:%d/%m/%Y} está "
                    f"fechado em {s.get(Entity, ent).name}.")

    series: dict[str, str] = {}
    cats = ccs = 0
    try:
        for e in rows:
            e.entity_id, e.account_id = dest.id, acc.id
            if e.category_id:
                cat = s.get(Category, e.category_id)
                if not scope.category_visible(s, cat, dest.id):
                    e.category_id = _category_in(s, cat, dest.id)
                    cats += e.category_id is None
            if e.cost_center_id and not scope.visible(s.get(CostCenter, e.cost_center_id), dest.id):
                e.cost_center_id = None
                ccs += 1
            if e.contact_id:
                c = s.get(Contact, e.contact_id)
                if not scope.visible(c, dest.id):
                    e.contact_id = _contact_in(s, c, dest.id)
            if e.series_id:
                e.series_id = series.setdefault(e.series_id, uuid.uuid4().hex)
        ids = [e.id for e in rows]
        s.execute(update(Attachment).where(Attachment.entry_id.in_(ids)).values(entity_id=dest.id))
        s.execute(update(BankLine).where(BankLine.entry_id.in_(ids)).values(entry_id=None, status="pending"))
        s.commit()
    except Exception:
        s.rollback()
        raise
    return MoveResult(len(rows), cats, ccs)
