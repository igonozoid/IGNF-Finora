"""Contatos: pessoas e empresas com quem você troca dinheiro. Um cadastro, vários papéis."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from finora.core import documents
from finora.models import Contact, Entry

# papel -> (coluna no modelo, rótulo, explicação)
ROLES = {
    "customer": ("is_customer", "Me paga", "Pessoa ou empresa de quem você recebe dinheiro (empregador, cliente)."),
    "supplier": ("is_supplier", "Eu pago", "Quem você paga: loja, prestador de serviço, conta de luz, aluguel…"),
    "employee": ("is_employee", "Trabalha para mim", "Quem presta serviço para você com frequência: diarista, babá…"),
}
PERSON_TYPES = {"PF": "Pessoa física", "PJ": "Pessoa jurídica"}


@dataclass(frozen=True)
class ContactView:
    id: int
    name: str
    person_type: str
    document: str | None
    roles: frozenset[str]
    entries: int
    last_date: date | None

    @property
    def initials(self) -> str:
        words = [w for w in self.name.split() if w[:1].isalnum()]
        return "".join(w[0] for w in words[:2]).upper() or "?"

    @property
    def document_fmt(self) -> str:
        return documents.fmt(self.document) if self.document else ""


def _roles(c: Contact) -> frozenset[str]:
    return frozenset(k for k, (col, *_r) in ROLES.items() if getattr(c, col))


def names(s: Session, entity_id: int) -> list[str]:
    return list(s.scalars(select(Contact.name).where(Contact.entity_id == entity_id).order_by(Contact.name)))


def list_contacts(s: Session, entity_id: int, search: str = "", role: str | None = None) -> list[ContactView]:
    q = (select(Contact, func.count(Entry.id), func.max(Entry.due_date))
         .outerjoin(Entry, Entry.contact_id == Contact.id)
         .where(Contact.entity_id == entity_id)
         .group_by(Contact.id)
         .order_by(func.lower(Contact.name)))
    if role in ROLES:
        q = q.where(getattr(Contact, ROLES[role][0]))
    if search.strip():
        like = f"%{search.strip().lower()}%"
        d = documents.digits(search)
        conds = [func.lower(Contact.name).like(like)]
        if d:
            conds.append(Contact.document.like(f"%{d}%"))
        q = q.where(or_(*conds))
    return [ContactView(c.id, c.name, c.person_type, c.document, _roles(c), n, last)
            for c, n, last in s.execute(q)]


def counts(s: Session, entity_id: int) -> dict[str, int]:
    """Quantos contatos há no total e em cada papel (para os filtros)."""
    out = {"all": s.scalar(select(func.count(Contact.id)).where(Contact.entity_id == entity_id))}
    for k, (col, *_r) in ROLES.items():
        out[k] = s.scalar(select(func.count(Contact.id)).where(Contact.entity_id == entity_id, getattr(Contact, col)))
    return out


def _check(s: Session, entity_id: int, name: str, person_type: str, document: str | None,
           exclude_id: int | None = None) -> tuple[str, str | None]:
    name = name.strip()
    if not name:
        raise ValueError("Digite o nome do contato.")
    if person_type not in PERSON_TYPES:
        raise ValueError("Tipo de pessoa inválido.")
    doc = documents.digits(document) or None
    if doc and not documents.is_valid(doc, person_type):
        raise ValueError(("CPF" if person_type == "PF" else "CNPJ") + " inválido. Confira os números.")
    same_name = select(Contact.id).where(Contact.entity_id == entity_id, func.lower(Contact.name) == name.lower())
    same_doc = select(Contact.id).where(Contact.entity_id == entity_id, Contact.document == doc)
    if exclude_id is not None:
        same_name = same_name.where(Contact.id != exclude_id)
        same_doc = same_doc.where(Contact.id != exclude_id)
    if s.scalar(same_name) is not None:
        raise ValueError(f"Já existe um contato chamado \"{name}\".")
    if doc and s.scalar(same_doc) is not None:
        raise ValueError("Já existe um contato com esse documento.")
    return name, doc


def _apply_roles(c: Contact, roles: set[str]) -> None:
    for k, (col, *_r) in ROLES.items():
        setattr(c, col, k in roles)


def create(s: Session, entity_id: int, *, name: str, person_type: str = "PF", document: str | None = None,
           roles: set[str] = frozenset()) -> int:
    name, doc = _check(s, entity_id, name, person_type, document)
    c = Contact(entity_id=entity_id, name=name, person_type=person_type, document=doc)
    _apply_roles(c, set(roles))
    s.add(c)
    s.commit()
    return c.id


def update(s: Session, contact_id: int, *, name: str, person_type: str, document: str | None,
           roles: set[str]) -> None:
    c = s.get(Contact, contact_id)
    c.name, c.document = _check(s, c.entity_id, name, person_type, document, exclude_id=c.id)
    c.person_type = person_type
    _apply_roles(c, set(roles))
    s.commit()


def delete(s: Session, contact_id: int) -> None:
    """Só exclui contato sem lançamentos, para não perder o histórico."""
    used = s.scalar(select(func.count(Entry.id)).where(Entry.contact_id == contact_id))
    if used:
        raise ValueError(f"Esse contato aparece em {used} {'lançamento' if used == 1 else 'lançamentos'} "
                         "e por isso não pode ser excluído.")
    s.delete(s.get(Contact, contact_id))
    s.commit()


def get_or_create(s: Session, entity_id: int, name: str | None, kind: str | None = None) -> int | None:
    """Usado pelos lançamentos: acha o contato pelo nome (sem diferenciar maiúsculas) ou cria um novo.
    Com `kind`, marca o papel: despesa -> "Eu pago", receita -> "Me paga". Nome vazio = sem contato."""
    name = (name or "").strip()
    if not name:
        return None
    c = s.scalars(select(Contact).where(Contact.entity_id == entity_id,
                                        func.lower(Contact.name) == name.lower())).first()
    if c is None:
        c = Contact(entity_id=entity_id, person_type="PF", name=name)
        s.add(c)
    role = {"expense": "supplier", "income": "customer"}.get(kind)
    if role:
        setattr(c, ROLES[role][0], True)
    s.flush()
    return c.id
