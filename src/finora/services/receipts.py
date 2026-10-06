"""Recibo de um lançamento (receita ou despesa).

- Receita (você recebeu): "Recebi de <contato> …" — quem assina é você.
- Despesa (você pagou): "Recebi de <você> …" — quem assina é o contato (ex.: a diarista assina e você guarda).
Transferências e compras no cartão não geram recibo.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from finora.core import documents, extenso, money
from finora.models import Contact, Entity, Entry

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]


@dataclass(frozen=True)
class Receipt:
    number: str
    amount: Decimal
    currency: str
    payer: str               # quem pagou ("Recebi de …")
    payer_doc: str
    payee: str               # quem recebeu e assina
    payee_doc: str
    reference: str           # "referente a …"
    city: str
    when: date

    @property
    def amount_text(self) -> str:
        return money.fmt(self.amount, self.currency)

    @property
    def amount_words(self) -> str:
        return extenso.money(self.amount, self.currency)

    @property
    def place_date(self) -> str:
        d = f"{self.when.day} de {MONTHS[self.when.month - 1]} de {self.when.year}"
        return f"{self.city}, {d}" if self.city.strip() else d

    @property
    def body(self) -> str:
        doc = f", {_doc_label(self.payer_doc)} {self.payer_doc}" if self.payer_doc else ""
        return (f"Recebi de {self.payer}{doc} a importância de {self.amount_text} ({self.amount_words}), "
                f"referente a {self.reference}.")


def _doc_label(doc: str) -> str:
    return "CNPJ" if len(documents.digits(doc)) == 14 else "CPF"


def can_issue(e: Entry) -> str | None:
    """None se dá para emitir; senão, o motivo (texto para o usuário)."""
    if e.kind == "transfer":
        return "Transferências entre suas contas não têm recibo."
    if e.status == "card":
        return "Compras no cartão não têm recibo: o comprovante é a fatura ou a nota da loja."
    return None


def build(s: Session, entry_id: int, *, city: str = "", when: date | None = None, my_doc: str = "",
          contact_name: str | None = None, contact_doc: str | None = None) -> Receipt:
    """Monta o recibo. `contact_name`/`contact_doc` permitem completar quem não está cadastrado."""
    e = s.get(Entry, entry_id)
    reason = can_issue(e)
    if reason:
        raise ValueError(reason)
    me = s.get(Entity, e.entity_id)
    c = s.get(Contact, e.contact_id) if e.contact_id else None
    other = (contact_name if contact_name is not None else (c.name if c else "")).strip()
    other_doc = contact_doc if contact_doc is not None else (documents.fmt(c.document) if c and c.document else "")
    if not other:
        raise ValueError("Informe o nome de quem " + ("pagou." if e.kind == "income" else "recebeu."))
    when = when or e.paid_date or e.due_date
    reference = (e.description or "").strip() or "pagamento"
    number = f"{e.id:06d}"
    my_doc = documents.fmt(my_doc) if my_doc else ""
    other_doc = documents.fmt(other_doc) if other_doc else ""
    if e.kind == "income":       # você recebeu: o contato pagou, você assina
        return Receipt(number, Decimal(e.amount), me.currency, other, other_doc, me.name, my_doc, reference,
                       city, when)
    return Receipt(number, Decimal(e.amount), me.currency, me.name, my_doc, other, other_doc, reference, city, when)


@dataclass(frozen=True)
class Parties:
    i_received: bool         # True: receita (você recebeu e assina); False: despesa (o contato assina)
    contact: str
    contact_doc: str
    when: date


def parties(s: Session, entry_id: int) -> Parties:
    """O que a janela precisa para começar: papéis, contato cadastrado e data sugerida."""
    e = s.get(Entry, entry_id)
    reason = can_issue(e)
    if reason:
        raise ValueError(reason)
    c = s.get(Contact, e.contact_id) if e.contact_id else None
    return Parties(e.kind == "income", c.name if c else "", documents.fmt(c.document) if c and c.document else "",
                   e.paid_date or e.due_date)
