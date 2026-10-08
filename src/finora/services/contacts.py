"""Contatos: pessoas e empresas com quem você troca dinheiro. Um cadastro, vários papéis."""
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from finora.core import documents
from finora.models import Contact, Entry
from finora.services import scope

# papel -> (coluna no modelo, rótulo, explicação)
ROLES = {
    "customer": ("is_customer", "Me paga", "Pessoa ou empresa de quem você recebe dinheiro (empregador, cliente)."),
    "supplier": ("is_supplier", "Eu pago", "Quem você paga: loja, prestador de serviço, conta de luz, aluguel…"),
    "employee": ("is_employee", "Trabalha para mim", "Quem presta serviço para você com frequência: diarista, babá…"),
}
PERSON_TYPES = {"PF": "Pessoa física", "PJ": "Pessoa jurídica"}
# Dados extras (todos opcionais): campo -> tamanho máximo
DETAILS = {"phone": 30, "email": 120, "zip_code": 9, "address": 200, "city": 80, "state": 2,
           "pix_key": 120, "bank_info": 120, "notes": 1000}
UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
       "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class ContactView:
    id: int
    name: str
    person_type: str
    document: str | None
    roles: frozenset[str]
    entries: int
    last_date: date | None
    details: dict = field(default_factory=dict, compare=False)     # telefone, e-mail, endereço, banco…
    shared: bool = False             # compartilhado com todas as entidades

    def get(self, key: str) -> str:
        return self.details.get(key) or ""

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
    return list(s.scalars(select(Contact.name).where(scope.contacts(entity_id)).order_by(Contact.name)))


def list_contacts(s: Session, entity_id: int, search: str = "", role: str | None = None) -> list[ContactView]:
    q = (select(Contact, func.count(Entry.id), func.max(Entry.due_date))
         .outerjoin(Entry, (Entry.contact_id == Contact.id) & (Entry.entity_id == entity_id))
         .where(scope.contacts(entity_id))
         .group_by(Contact.id)
         .order_by(func.lower(Contact.name)))
    if role in ROLES:
        q = q.where(getattr(Contact, ROLES[role][0]))
    if search.strip():
        like = f"%{search.strip().lower()}%"
        d = documents.digits(search)
        conds = [func.lower(Contact.name).like(like), func.lower(Contact.email).like(like)]
        if d:
            conds += [Contact.document.like(f"%{d}%"), Contact.phone.like(f"%{d}%")]
        q = q.where(or_(*conds))
    return [ContactView(c.id, c.name, c.person_type, c.document, _roles(c), n, last,
                        {k: getattr(c, k) for k in DETAILS}, bool(c.shared))
            for c, n, last in s.execute(q)]


def counts(s: Session, entity_id: int) -> dict[str, int]:
    """Quantos contatos há no total e em cada papel (para os filtros)."""
    out = {"all": s.scalar(select(func.count(Contact.id)).where(scope.contacts(entity_id)))}
    for k, (col, *_r) in ROLES.items():
        out[k] = s.scalar(select(func.count(Contact.id)).where(scope.contacts(entity_id), getattr(Contact, col)))
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
    same_name = select(Contact.id).where(scope.contacts(entity_id), func.lower(Contact.name) == name.lower())
    same_doc = select(Contact.id).where(scope.contacts(entity_id), Contact.document == doc)
    if exclude_id is not None:
        same_name = same_name.where(Contact.id != exclude_id)
        same_doc = same_doc.where(Contact.id != exclude_id)
    if s.scalar(same_name) is not None:
        raise ValueError(f"Já existe um contato chamado \"{name}\".")
    if doc and s.scalar(same_doc) is not None:
        raise ValueError("Já existe um contato com esse documento.")
    return name, doc


def clean_details(details: dict | None) -> dict:
    """Valida e normaliza os dados extras. Vazio vira None."""
    out = {}
    for key, value in (details or {}).items():
        if key not in DETAILS:
            raise ValueError(f"Campo desconhecido: {key}")
        v = (value or "").strip()
        if key == "email" and v and not _EMAIL.match(v):
            raise ValueError("E-mail inválido. Confira se tem @ e o domínio (ex.: nome@site.com).")
        if key == "state" and v:
            v = v.upper()
            if v not in UFS:
                raise ValueError("UF inválida. Use a sigla do estado, ex.: SP.")
        if key == "zip_code" and v:
            d = documents.digits(v)
            if len(d) != 8:
                raise ValueError("CEP inválido. Use 8 números, ex.: 13010-050.")
            v = f"{d[:5]}-{d[5:]}"
        if len(v) > DETAILS[key]:
            raise ValueError("Texto longo demais em um dos campos.")
        out[key] = v or None
    return out


def _apply_roles(c: Contact, roles: set[str]) -> None:
    for k, (col, *_r) in ROLES.items():
        setattr(c, col, k in roles)


def create(s: Session, entity_id: int, *, name: str, person_type: str = "PF", document: str | None = None,
           roles: set[str] = frozenset(), details: dict | None = None, shared: bool = False) -> int:
    name, doc = _check(s, entity_id, name, person_type, document)
    extra = clean_details(details)
    c = Contact(entity_id=entity_id, name=name, person_type=person_type, document=doc, shared=bool(shared), **extra)
    _apply_roles(c, set(roles))
    s.add(c)
    s.commit()
    return c.id


def update(s: Session, contact_id: int, *, name: str, person_type: str, document: str | None,
           roles: set[str], details: dict | None = None, shared: bool | None = None) -> None:
    c = s.get(Contact, contact_id)
    if shared is not None:
        c.shared = shared
    c.name, c.document = _check(s, c.entity_id, name, person_type, document, exclude_id=c.id)
    for key, value in clean_details(details).items():
        setattr(c, key, value)
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
    c = s.scalars(select(Contact).where(scope.contacts(entity_id), func.lower(Contact.name) == name.lower())
                  .order_by((Contact.entity_id == entity_id).desc())).first()     # o da entidade antes do compartilhado
    if c is None:
        c = Contact(entity_id=entity_id, person_type="PF", name=name)
        s.add(c)
    role = {"expense": "supplier", "income": "customer"}.get(kind)
    if role:
        setattr(c, ROLES[role][0], True)
    s.flush()
    return c.id
