"""Entidades (multiempresa): cada pessoa ou empresa tem dados totalmente separados.

Free: 1 entidade. Plus: até 10. Pro: ilimitadas (core/licensing).
"""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core import documents
from finora.core.licensing import LimitError, allowed, current_edition
from finora.core.money import CURRENCIES
from finora.models import Account, Entity, Entry, User, UserEntity

PERSON_TYPES = {"PF": "Pessoa física", "PJ": "Pessoa jurídica"}


@dataclass(frozen=True)
class EntityView:
    id: int
    name: str
    currency: str
    person_type: str
    document: str | None
    is_active: bool
    users: int
    accounts: int
    entries: int

    @property
    def document_fmt(self) -> str:
        return documents.fmt(self.document) if self.document else ""


def limit() -> int | None:
    return allowed(current_edition(), "entities_max")


def active_count(s: Session) -> int:
    return s.scalar(select(func.count(Entity.id)).where(Entity.is_active))


def list_entities(s: Session, user_id: int | None = None, include_inactive: bool = True) -> list[EntityView]:
    """Todas (administração) ou só as que o usuário pode abrir."""
    q = select(Entity).order_by(Entity.is_active.desc(), func.lower(Entity.name))
    if not include_inactive:
        q = q.where(Entity.is_active)
    if user_id is not None:
        q = q.join(UserEntity, UserEntity.entity_id == Entity.id).where(UserEntity.user_id == user_id)
    out = []
    for e in s.scalars(q):
        users = s.scalar(select(func.count()).select_from(UserEntity).where(UserEntity.entity_id == e.id))
        accs = s.scalar(select(func.count(Account.id)).where(Account.entity_id == e.id))
        ents = s.scalar(select(func.count(Entry.id)).where(Entry.entity_id == e.id))
        out.append(EntityView(e.id, e.name, e.currency, e.person_type or "PF", e.document, e.is_active,
                              users, accs, ents))
    return out


def _check(s: Session, name: str, person_type: str, document: str | None, currency: str,
           exclude_id: int | None = None) -> tuple[str, str | None]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Dê um nome para a entidade (ex.: Padaria Sol, Maria — pessoal).")
    if person_type not in PERSON_TYPES:
        raise ValueError("Tipo de pessoa inválido.")
    if currency not in CURRENCIES:
        raise ValueError(f"Moeda não suportada: {currency}")
    doc = documents.digits(document or "") or None
    if doc and not documents.is_valid(doc, person_type):
        raise ValueError(("CPF" if person_type == "PF" else "CNPJ") + " inválido. Confira os números.")
    q = select(Entity.id).where(func.lower(Entity.name) == name.lower())
    if exclude_id is not None:
        q = q.where(Entity.id != exclude_id)
    if s.scalar(q) is not None:
        raise ValueError(f"Já existe uma entidade chamada \"{name}\".")
    return name, doc


def create(s: Session, *, name: str, person_type: str = "PF", document: str | None = None, currency: str = "BRL",
           account_name: str = "Conta principal", default_categories: bool = True,
           user_ids: list[int] | None = None) -> int:
    """Nova entidade com 1 conta e as categorias padrão. Os administradores ganham acesso; outros, se indicados."""
    lim = limit()
    if lim is not None and active_count(s) >= lim:
        raise LimitError(f"Sua edição permite até {lim} {'entidade' if lim == 1 else 'entidades'}. "
                         "Inative uma ou faça upgrade.")
    name, doc = _check(s, name, person_type, document, currency)
    from finora.services.setup import _add_default_categories
    e = Entity(name=name, currency=currency, person_type=person_type, document=doc, is_active=True)
    s.add(e)
    s.flush()
    s.add(Account(entity_id=e.id, name=account_name.strip() or "Conta principal", kind="bank", currency=currency,
                  opening_balance=0, is_active=True))
    if default_categories:
        _add_default_categories(s, e.id)
    ids = set(user_ids or []) | set(s.scalars(select(User.id).where(User.is_admin)))
    for uid in ids:
        s.add(UserEntity(user_id=uid, entity_id=e.id))
    s.commit()
    return e.id


def update(s: Session, entity_id: int, *, name: str, person_type: str, document: str | None,
           is_active: bool = True) -> None:
    e = s.get(Entity, entity_id)
    name, doc = _check(s, name, person_type, document, e.currency, exclude_id=entity_id)
    if e.is_active and not is_active and active_count(s) <= 1:
        raise ValueError("Precisa ficar pelo menos uma entidade ativa.")
    if not e.is_active and is_active:
        lim = limit()
        if lim is not None and active_count(s) >= lim:
            raise LimitError(f"Sua edição permite até {lim} entidades ativas.")
    e.name, e.person_type, e.document, e.is_active = name, person_type, doc, is_active
    s.commit()
