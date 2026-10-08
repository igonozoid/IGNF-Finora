"""Recibo de um lançamento, no mesmo formato do IgnControl (e do sistema legado):

- cabeçalho com o logotipo e os dados da entidade (endereço, contatos, CPF/CNPJ e inscrição);
- RECIBO · Data | Documento;
- Despesa: "Pagamento para" (o contato) · "Emitido por" (a entidade) — quem assina é o contato;
- Receita: "Recebido de" (o contato) · "Recebido por" (a entidade) — quem assina é a entidade;
- Valor, Data, Documento, Importância (por extenso), Referente a, Observação e a linha de assinatura com o
  nome em maiúsculas e o CPF/CNPJ de quem assina; 1 ou 2 vias (meia folha A4 cada, com linha de corte).

Transferências e compras no cartão não geram recibo.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from finora.core import documents, extenso, money
from finora.models import Account, Contact, Entry
from finora.services.entity_admin import Letterhead, letterhead

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]


@dataclass(frozen=True)
class Receipt:
    number: str
    is_expense: bool
    party_label: str          # "Pagamento para" | "Recebido de"
    party: str
    entity_label: str         # "Emitido por" | "Recebido por"
    entity: str
    amount: Decimal
    currency: str
    when: date
    document: str
    reference: str
    notes: str
    signer: str               # quem assina (despesa: o contato; receita: a entidade)
    signer_doc: str
    head: Letterhead

    @property
    def amount_text(self) -> str:
        return money.fmt(self.amount, self.currency)

    @property
    def amount_words(self) -> str:
        return extenso.money(self.amount, self.currency)

    @property
    def date_text(self) -> str:
        return self.when.strftime("%d/%m/%Y")


def can_issue(e: Entry) -> str | None:
    """None se dá para emitir; senão, o motivo (texto para o usuário)."""
    if e.kind == "transfer":
        return "Transferências entre suas contas não têm recibo."
    if e.status == "card":
        return "Compras no cartão não têm recibo: o comprovante é a fatura ou a nota da loja."
    return None


def build(s: Session, entry_id: int, *, when: date | None = None, party: str | None = None,
          party_doc: str | None = None, document: str | None = None, reference: str | None = None,
          notes: str = "", entity_doc: str = "") -> Receipt:
    """Monta o recibo. Os parâmetros permitem revisar o que vem do lançamento (como no diálogo do IgnControl)."""
    e = s.get(Entry, entry_id)
    reason = can_issue(e)
    if reason:
        raise ValueError(reason)
    head = letterhead(s, e.entity_id)
    c = s.get(Contact, e.contact_id) if e.contact_id else None
    expense = e.kind == "expense"
    name = (party if party is not None else (c.name if c else "")).strip()
    if not name:
        raise ValueError("Informe o nome de quem " + ("recebeu o pagamento." if expense else "pagou."))
    p_doc = party_doc if party_doc is not None else (c.document if c and c.document else "")
    p_doc = documents.fmt(p_doc) if p_doc else ""
    my_doc = head.document or (documents.fmt(entity_doc) if entity_doc else "")
    currency = s.get(Account, e.account_id).currency
    return Receipt(
        number=f"{e.id:06d}", is_expense=expense,
        party_label="Pagamento para" if expense else "Recebido de", party=name,
        entity_label="Emitido por" if expense else "Recebido por", entity=head.name,
        amount=Decimal(e.amount), currency=currency, when=when or e.paid_date or e.due_date,
        document=(document if document is not None else (e.document_no or "")).strip(),
        reference=(reference if reference is not None else (e.description or "")).strip() or "pagamento",
        notes=(notes or "").strip(),
        signer=name if expense else head.name, signer_doc=p_doc if expense else my_doc, head=head)


@dataclass(frozen=True)
class Parties:
    is_expense: bool
    contact: str
    contact_doc: str
    when: date
    document: str
    reference: str


def parties(s: Session, entry_id: int) -> Parties:
    """O que a janela precisa para começar (já preenchido a partir do lançamento)."""
    e = s.get(Entry, entry_id)
    reason = can_issue(e)
    if reason:
        raise ValueError(reason)
    c = s.get(Contact, e.contact_id) if e.contact_id else None
    return Parties(e.kind == "expense", c.name if c else "", documents.fmt(c.document) if c and c.document else "",
                   e.paid_date or e.due_date, e.document_no or "", e.description or "")
