"""Contatos (por enquanto só o necessário para os lançamentos: listar e criar pelo nome)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.models import Contact


def names(s: Session, entity_id: int) -> list[str]:
    return list(s.scalars(select(Contact.name).where(Contact.entity_id == entity_id).order_by(Contact.name)))


def get_or_create(s: Session, entity_id: int, name: str | None) -> int | None:
    """Acha o contato pelo nome (sem diferenciar maiúsculas) ou cria um novo. Nome vazio = sem contato."""
    name = (name or "").strip()
    if not name:
        return None
    found = s.scalar(select(Contact.id).where(Contact.entity_id == entity_id,
                                              func.lower(Contact.name) == name.lower()))
    if found is not None:
        return found
    c = Contact(entity_id=entity_id, person_type="PF", name=name)
    s.add(c)
    s.flush()
    return c.id
