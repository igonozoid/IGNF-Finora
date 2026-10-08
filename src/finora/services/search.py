"""Busca global (Ctrl K): lançamentos de qualquer mês, contatos, contas e categorias."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from finora.core import documents, money
from finora.models import Account, Category, Contact, Entity, Entry
from finora.services import entries, scope
from finora.services.accounts import KINDS as ACC_KINDS

KINDS = {"entry": "Lançamento", "contact": "Contato", "account": "Conta", "category": "Categoria"}
MIN_CHARS = 2


@dataclass(frozen=True)
class Hit:
    kind: str           # entry | contact | account | category
    id: int
    title: str
    subtitle: str
    when: date | None = None


def search(s: Session, entity_id: int, text: str, per_kind: int = 6) -> list[Hit]:
    """Resultados agrupados: contas, categorias, contatos e lançamentos (os mais recentes primeiro)."""
    text = text.strip()
    if len(text) < MIN_CHARS:
        return []
    like = f"%{text.lower()}%"
    digits = documents.digits(text)
    cur = s.get(Entity, entity_id).currency
    hits: list[Hit] = []

    for a in s.scalars(select(Account).where(Account.entity_id == entity_id, func.lower(Account.name).like(like))
                       .order_by(Account.name).limit(per_kind)):
        hits.append(Hit("account", a.id, a.name, ACC_KINDS.get(a.kind, a.kind) + ("" if a.is_active else " · inativa")))

    for c in s.scalars(select(Category).where(scope.categories(entity_id), func.lower(Category.name).like(like))
                       .order_by(Category.code).limit(per_kind)):
        group = s.get(Category, c.parent_id).name if c.parent_id else None
        hits.append(Hit("category", c.id, c.name, f"Subcategoria de {group}" if group else "Grupo de categorias"))

    conds = [func.lower(Contact.name).like(like)]
    if digits:
        conds.append(Contact.document.like(f"%{digits}%"))
    for c in s.scalars(select(Contact).where(scope.contacts(entity_id), or_(*conds))
                       .order_by(Contact.name).limit(per_kind)):
        hits.append(Hit("contact", c.id, c.name, documents.fmt(c.document) if c.document else "Contato"))

    q = (entries.query(entity_id)
         .where(or_(func.lower(Entry.description).like(like), func.lower(Contact.name).like(like),
                    func.lower(Entry.document_no).like(like)))
         .order_by(Entry.due_date.desc(), Entry.id.desc()).limit(per_kind * 2))
    for row in s.execute(q):
        e = entries.to_view(row)
        value = money.fmt(e.amount if e.kind == "income" else -e.amount, cur)
        bits = [e.due_date.strftime("%d/%m/%Y"), e.account, value]
        if e.contact:
            bits.insert(1, e.contact)
        hits.append(Hit("entry", e.id, e.description + (f" ({e.installment})" if e.installment else ""),
                        " · ".join(bits), e.due_date))
    return hits
