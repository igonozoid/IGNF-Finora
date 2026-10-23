"""Contatos: pessoas e empresas com quem você troca dinheiro. Um cadastro, vários papéis."""
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from finora.core import documents, money
from finora.models import Attachment, Contact, ContactBank, ContactPerson, ContactReference, Entry
from finora.services import scope

# papel -> (coluna no modelo, rótulo, explicação)
ROLES = {
    "customer": ("is_customer", "Me paga", "Pessoa ou empresa de quem você recebe dinheiro (empregador, cliente)."),
    "supplier": ("is_supplier", "Eu pago", "Quem você paga: loja, prestador de serviço, conta de luz, aluguel…"),
    "employee": ("is_employee", "Trabalha para mim", "Quem presta serviço para você com frequência: diarista, babá…"),
}
PERSON_TYPES = {"PF": "Pessoa física", "PJ": "Pessoa jurídica"}
# Dados extras (todos opcionais): campo -> tamanho máximo
DETAILS = {"phone": 30, "email": 120, "document2": 30, "contact_person": 80, "zip_code": 9, "address": 200,
           "district": 80, "city": 80, "state": 2, "pix_key": 120, "bank_name": 60, "bank_branch": 20,
           "bank_account": 30, "bank_holder": 120, "notes": 1000}
# Crédito (edições pagas): classificação e frequência de compra, como no cadastro de clientes do IgnControl
RATINGS = {"otimo": "Ótimo", "bom": "Bom", "regular": "Regular", "ruim": "Ruim"}
FREQUENCIES = {"semanal": "Semanal", "quinzenal": "Quinzenal", "mensal": "Mensal", "eventual": "Eventual"}
CREDIT = ("credit_limit", "credit_checked_on", "credit_pending", "credit_pending_where", "mother_name", "rating",
          "purchase_frequency")
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
    needs_review: bool = False       # criado sozinho (importação): conferir
    credit: dict = field(default_factory=dict, compare=False)      # limite, consulta, pendência… (CREDIT)

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
    elif role == "review":
        q = q.where(Contact.needs_review.is_(True))
    if search.strip():
        like = f"%{search.strip().lower()}%"
        d = documents.digits(search)
        conds = [func.lower(Contact.name).like(like), func.lower(Contact.email).like(like),
                 func.lower(Contact.contact_person).like(like)]
        if d:
            conds += [Contact.document.like(f"%{d}%"), Contact.phone.like(f"%{d}%")]
        q = q.where(or_(*conds))
    return [ContactView(c.id, c.name, c.person_type, c.document, _roles(c), n, last,
                        {k: getattr(c, k) for k in DETAILS}, bool(c.shared), bool(c.needs_review),
                        {k: getattr(c, k) for k in CREDIT})
            for c, n, last in s.execute(q)]


def counts(s: Session, entity_id: int) -> dict[str, int]:
    """Quantos contatos há no total e em cada papel (para os filtros)."""
    out = {"all": s.scalar(select(func.count(Contact.id)).where(scope.contacts(entity_id)))}
    for k, (col, *_r) in ROLES.items():
        out[k] = s.scalar(select(func.count(Contact.id)).where(scope.contacts(entity_id), getattr(Contact, col)))
    out["review"] = s.scalar(select(func.count(Contact.id)).where(scope.contacts(entity_id),
                                                                  Contact.needs_review.is_(True)))
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


def _date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        d, m, y = (int(p) for p in text.split("/"))
        return date(y, m, d)
    except ValueError:
        raise ValueError("Data inválida. Use dia/mês/ano, ex.: 15/03/2026.") from None


def clean_credit(credit: dict | None, person_type: str = "PF", today: date | None = None) -> dict:
    """Valida os dados de crédito. Aceita texto da tela (valor e data no padrão brasileiro) ou valores prontos.
    Sem pendência, o local some; nome da mãe é só de pessoa física."""
    out = {}
    for key, value in (credit or {}).items():
        if key not in CREDIT:
            raise ValueError(f"Campo desconhecido: {key}")
        if key == "credit_limit":
            if isinstance(value, str):
                try:
                    value = money.parse(value) if value.strip() else None
                except ValueError:
                    raise ValueError("Limite de crédito inválido. Ex.: 5.000,00") from None
            if value is not None and value < 0:
                raise ValueError("O limite de crédito não pode ser negativo.")
        elif key == "credit_checked_on":
            value = _date(value) if isinstance(value, str) else value
            if value and value > (today or date.today()):
                raise ValueError("A data da consulta de crédito não pode ser no futuro.")
        elif key == "credit_pending":
            value = bool(value)
        else:
            value = (value or "").strip() or None
            choices = {"rating": RATINGS, "purchase_frequency": FREQUENCIES}.get(key)
            if value and choices is not None and value not in choices:
                raise ValueError("Opção inválida.")
            if value and len(value) > {"credit_pending_where": 80, "mother_name": 150}.get(key, 10):
                raise ValueError("Texto longo demais em um dos campos.")
        out[key] = value
    if "credit_pending" in out and not out["credit_pending"]:
        out["credit_pending_where"] = None
    if person_type != "PF" and "mother_name" in out:
        out["mother_name"] = None
    return out


# ---------- listas do contato (Fase 4.2; edições pagas) ----------
REFERENCE_KINDS = {"comercial": "Comercial", "bancaria": "Bancária"}
# lista -> (modelo, [(campo, rótulo, tamanho)]); o 1º campo é obrigatório (linha sem ele é ignorada)
LISTS = {
    "banks": (ContactBank, [("bank_name", "Banco", 60), ("bank_branch", "Agência", 20),
                            ("bank_account", "Conta", 30), ("holder", "Titular", 120), ("pix_key", "Chave Pix", 120)]),
    "references": (ContactReference, [("name", "Nome", 120), ("kind", "Tipo", 10), ("phone", "Telefone", 30),
                                      ("notes", "Observação", 200)]),
    "people": (ContactPerson, [("name", "Nome", 80), ("job", "Cargo", 60), ("extension", "Ramal", 10),
                               ("email", "E-mail", 120), ("phone", "Telefone", 30)]),
}


def get_lists(s: Session, contact_id: int) -> dict[str, list[dict]]:
    out = {}
    for key, (model, fields) in LISTS.items():
        rows = s.scalars(select(model).where(model.contact_id == contact_id).order_by(model.id))
        out[key] = [{f: getattr(r, f) for f, _l, _n in fields} for r in rows]
    return out


def clean_lists(lists: dict | None, person_type: str = "PF") -> dict[str, list[dict]]:
    """Valida as listas. Linha sem o 1º campo (banco ou nome) é ignorada; pessoas de contato só em PJ."""
    out = {}
    for key, rows in (lists or {}).items():
        if key not in LISTS:
            raise ValueError(f"Lista desconhecida: {key}")
        fields = LISTS[key][1]
        clean = []
        for row in rows:
            r = {f: (row.get(f) or "").strip() or None for f, _l, _n in fields}
            if not r[fields[0][0]]:
                continue
            for f, label, size in fields:
                if r[f] and len(r[f]) > size:
                    raise ValueError(f"Texto longo demais em \"{label}\".")
            if key == "references":
                r["kind"] = r["kind"] or "comercial"
                if r["kind"] not in REFERENCE_KINDS:
                    raise ValueError("Tipo de referência inválido: use comercial ou bancária.")
            if key == "people" and r["email"] and not _EMAIL.match(r["email"]):
                raise ValueError(f"E-mail inválido na pessoa de contato \"{r['name']}\".")
            clean.append(r)
        out[key] = clean
    if person_type != "PJ" and "people" in out:
        out["people"] = []
    return out


def _save_lists(s: Session, contact_id: int, lists: dict[str, list[dict]]) -> None:
    from sqlalchemy import delete as sql_delete
    for key, rows in lists.items():
        model = LISTS[key][0]
        s.execute(sql_delete(model).where(model.contact_id == contact_id))
        for r in rows:
            s.add(model(contact_id=contact_id, **r))


def _apply_roles(c: Contact, roles: set[str]) -> None:
    for k, (col, *_r) in ROLES.items():
        setattr(c, col, k in roles)


def create(s: Session, entity_id: int, *, name: str, person_type: str = "PF", document: str | None = None,
           roles: set[str] = frozenset(), details: dict | None = None, shared: bool = False,
           credit: dict | None = None, lists: dict | None = None) -> int:
    name, doc = _check(s, entity_id, name, person_type, document)
    extra = clean_details(details) | clean_credit(credit, person_type)
    rows = clean_lists(lists, person_type)
    c = Contact(entity_id=entity_id, name=name, person_type=person_type, document=doc, shared=bool(shared), **extra)
    _apply_roles(c, set(roles))
    s.add(c)
    s.flush()
    _save_lists(s, c.id, rows)
    s.commit()
    return c.id


def update(s: Session, contact_id: int, *, name: str, person_type: str, document: str | None,
           roles: set[str], details: dict | None = None, shared: bool | None = None,
           credit: dict | None = None, lists: dict | None = None) -> None:
    """`credit`/`lists` None = não mexe (ex.: edição Free, que não mostra essas abas). Cada lista enviada
    substitui a guardada."""
    c = s.get(Contact, contact_id)
    if shared is not None:
        c.shared = shared
    c.name, c.document = _check(s, c.entity_id, name, person_type, document, exclude_id=c.id)
    for key, value in (clean_details(details) | clean_credit(credit, person_type)).items():
        setattr(c, key, value)
    rows = clean_lists(lists, person_type)
    if person_type != "PF":
        c.mother_name = None
    else:
        rows["people"] = []                # pessoas de contato só em empresa
    _save_lists(s, c.id, rows)
    c.person_type = person_type
    c.needs_review = False                 # salvar no cadastro = conferido
    _apply_roles(c, set(roles))
    s.commit()


def delete(s: Session, contact_id: int) -> None:
    """Só exclui contato sem lançamentos, para não perder o histórico."""
    used = s.scalar(select(func.count(Entry.id)).where(Entry.contact_id == contact_id)
                    .execution_options(include_deleted=True))       # os da lixeira podem voltar
    if used:
        raise ValueError(f"Esse contato aparece em {used} {'lançamento' if used == 1 else 'lançamentos'} "
                         "(contando os da lixeira) e por isso não pode ser excluído.")
    _save_lists(s, contact_id, {k: [] for k in LISTS})
    for a in s.scalars(select(Attachment).where(Attachment.contact_id == contact_id)):
        s.delete(a)
    s.delete(s.get(Contact, contact_id))
    s.commit()


PHOTO_MAX = 500_000


def set_photo(s: Session, contact_id: int, png: bytes | None) -> None:
    """Foto do contato (PNG já reduzido pela tela). None tira a foto."""
    if png and len(png) > PHOTO_MAX:
        raise ValueError("A foto ficou grande demais. Use uma imagem menor.")
    s.get(Contact, contact_id).photo = png or None
    s.commit()


def get_photo(s: Session, contact_id: int) -> bytes | None:
    return s.get(Contact, contact_id).photo


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


# ---------- mesclar duplicados (Fase 2.13) ----------
_SUFFIXES = re.compile(r"\b(ltda|me|epp|eireli|s ?a|sa|cia)\b")


def _key(name: str) -> str:
    import unicodedata
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    plain = re.sub(r"[^a-z0-9 ]+", " ", plain)
    return " ".join(_SUFFIXES.sub(" ", plain).split())


def duplicates(s: Session, entity_id: int, contact_id: int) -> list[int]:
    """Prováveis duplicados do contato: mesmo nome sem acento/pontuação/"Ltda", ou mesmo documento."""
    me = s.get(Contact, contact_id)
    key = _key(me.name)
    out = []
    for c in s.scalars(select(Contact).where(scope.contacts(entity_id), Contact.id != contact_id)):
        if (key and _key(c.name) == key) or (me.document and c.document == me.document):
            out.append(c.id)
    return out


@dataclass(frozen=True)
class MergeResult:
    entries: int
    others: int              # regras, estoque, vendas, pecuária


def merge(s: Session, keep_id: int, drop_id: int) -> MergeResult:
    """Junta `drop` em `keep`: lançamentos (até os da lixeira), regras, estoque, vendas e pecuária passam para o
    mantido, que ganha os papéis e os dados que estavam vazios; `drop` some. Fica registrado no histórico."""
    from sqlalchemy import update as sql_update
    from finora.models import CategoryRule, HerdEvent, ImportMap, Sale, StockMove
    from finora.services import audit
    if keep_id == drop_id:
        raise ValueError("Escolha dois contatos diferentes.")
    keep, drop = s.get(Contact, keep_id), s.get(Contact, drop_id)
    if keep is None or drop is None:
        raise ValueError("Contato não encontrado.")
    if not keep.shared and (drop.shared or drop.entity_id != keep.entity_id):
        raise ValueError(f"\"{drop.name}\" aparece em outras entidades: mantenha o contato compartilhado.")
    if keep.document and drop.document and keep.document != drop.document:
        raise ValueError("Os dois contatos têm CPF/CNPJ diferentes: não parecem a mesma pessoa.")
    n_entries = s.execute(sql_update(Entry).where(Entry.contact_id == drop_id).values(contact_id=keep_id)
                          .execution_options(synchronize_session=False)).rowcount
    others = 0
    for model in (CategoryRule, StockMove, Sale, HerdEvent):
        others += s.execute(sql_update(model).where(model.contact_id == drop_id).values(contact_id=keep_id)
                            .execution_options(synchronize_session=False)).rowcount
    for model in [m for m, _f in LISTS.values()] + [Attachment]:     # contas, referências, pessoas e anexos
        s.execute(sql_update(model).where(model.contact_id == drop_id).values(contact_id=keep_id)
                  .execution_options(synchronize_session=False))
    s.expire_all()                                         # nada carregado antes fica com o contato antigo
    for m in s.scalars(select(ImportMap).where(ImportMap.kind == "pessoas", ImportMap.target == str(drop_id))):
        m.target = str(keep_id)                            # reimportar o MCC continua achando o contato
    for k, (col, *_r) in ROLES.items():
        setattr(keep, col, getattr(keep, col) or getattr(drop, col))
    fill = {k: getattr(drop, k) for k in (*DETAILS, *CREDIT, "photo") if not getattr(keep, k) and getattr(drop, k)}
    if drop.notes and keep.notes and drop.notes not in keep.notes:
        fill["notes"] = f"{keep.notes}\n{drop.notes}"[:DETAILS["notes"]]
    document = keep.document or drop.document
    person_type = keep.person_type if keep.document or not drop.document else drop.person_type
    drop_name = drop.name
    s.delete(drop)
    s.flush()                                              # o documento só pode passar depois que o outro sumir
    for k, v in fill.items():
        setattr(keep, k, v)
    keep.document, keep.person_type = document, person_type
    keep.needs_review = False                              # mesclar = conferido
    s.commit()
    audit.note(s, keep.entity_id, f"Mesclou o contato \"{drop_name}\" em \"{keep.name}\": {n_entries} lançamento(s)"
                                  + (f" e {others} outro(s) registro(s)" if others else "") + " passaram para ele.")
    return MergeResult(n_entries, others)
