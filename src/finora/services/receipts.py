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
    if e.kind in ("deposit", "withdrawal"):
        return "Depósitos e retiradas (ajustes de saldo) não têm recibo."
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


# ---------- duplicata (Fase 3.13, do MCC) ----------
DUPLICATA_KINDS = {"mercantil": "Duplicata de venda mercantil", "servico": "Duplicata de prestação de serviços"}


@dataclass(frozen=True)
class Duplicata:
    """Duplicata (Lei 5.474/68): a entidade vende (emitente) e o contato compra (sacado)."""
    kind: str                     # mercantil | servico
    number: str                   # nº de ordem da duplicata (ex.: "NF-77-2/3")
    invoice: str                  # nº da fatura / nota
    amount: Decimal
    invoice_amount: Decimal       # valor da fatura (a soma das parcelas, se for uma série)
    currency: str
    issued: date
    due: date
    place: str                    # praça de pagamento (cidade/UF da entidade)
    sacado: str
    sacado_doc: str
    sacado_ie: str
    sacado_address: str           # rua, bairro
    sacado_city: str              # cidade/UF e CEP
    reference: str
    head: Letterhead

    @property
    def title(self) -> str:
        return DUPLICATA_KINDS[self.kind]

    @property
    def amount_text(self) -> str:
        return money.fmt(self.amount, self.currency)

    @property
    def invoice_amount_text(self) -> str:
        return money.fmt(self.invoice_amount, self.currency)

    @property
    def amount_words(self) -> str:
        return extenso.money(self.amount, self.currency)

    @property
    def acceptance(self) -> str:
        what = "VENDA MERCANTIL" if self.kind == "mercantil" else "PRESTAÇÃO DE SERVIÇOS"
        return (f"Reconhecemos a exatidão desta DUPLICATA DE {what}, na importância acima, que pagaremos a "
                f"{self.head.name} ou à sua ordem, na praça e no vencimento indicados.")


def can_issue_duplicata(e: Entry) -> str | None:
    if e.kind != "income":
        return "Duplicata é de venda: só para receitas (você vende, o contato compra)."
    if e.status == "card":
        return "Compras no cartão não têm duplicata."
    if not e.contact_id:
        return "Escolha o contato (o comprador) no lançamento antes de emitir a duplicata."
    return None


def build_duplicata(s: Session, entry_id: int, kind: str = "mercantil", *, issued: date | None = None,
                    invoice: str | None = None, place: str | None = None) -> Duplicata:
    """Monta a duplicata da receita. Numa série de parcelas, o nº de ordem leva a parcela (n/N) e o valor da fatura
    é a soma da série."""
    from sqlalchemy import func, select
    from finora.services import entity_admin
    if kind not in DUPLICATA_KINDS:
        raise ValueError("Tipo de duplicata inválido.")
    e = s.get(Entry, entry_id)
    reason = can_issue_duplicata(e)
    if reason:
        raise ValueError(reason)
    c = s.get(Contact, e.contact_id)
    head = letterhead(s, e.entity_id)
    invoice = (invoice if invoice is not None else (e.document_no or f"{e.id:06d}")).strip()
    if e.installment and invoice.endswith(e.installment):            # parcela: o documento já vem "NF 77 2/3"
        invoice = invoice[:-len(e.installment)].rstrip(" -/") or invoice
    total = Decimal(e.amount)
    if e.series_id:
        total = Decimal(s.scalar(select(func.sum(Entry.amount)).where(Entry.series_id == e.series_id,
                                                                     Entry.status != "canceled")) or e.amount)
    number = f"{invoice}-{e.installment}" if e.installment else invoice
    me = entity_admin.details(s, e.entity_id)
    town = "/".join(x for x in (me.get("city"), me.get("state")) if x)
    return Duplicata(
        kind=kind, number=number, invoice=invoice, amount=Decimal(e.amount), invoice_amount=total,
        currency=s.get(Account, e.account_id).currency, issued=issued or e.competence_date or date.today(),
        due=e.due_date, place=(place if place is not None else town).strip(), sacado=c.name,
        sacado_doc=documents.fmt(c.document) if c.document else "", sacado_ie=c.document2 or "",
        sacado_address=", ".join(x for x in (c.address, c.district) if x),
        sacado_city=" — ".join(x for x in ("/".join(y for y in (c.city, c.state) if y),
                                           f"CEP {c.zip_code}" if c.zip_code else "") if x),
        reference=(e.description or "").strip(), head=head)


@dataclass(frozen=True)
class Parties:
    is_expense: bool
    contact: str
    contact_doc: str
    when: date
    document: str
    reference: str
    notes: str = ""


def parties(s: Session, entry_id: int) -> Parties:
    """O que a janela precisa para começar (já preenchido a partir do lançamento)."""
    e = s.get(Entry, entry_id)
    reason = can_issue(e)
    if reason:
        raise ValueError(reason)
    c = s.get(Contact, e.contact_id) if e.contact_id else None
    return Parties(e.kind == "expense", c.name if c else "", documents.fmt(c.document) if c and c.document else "",
                   e.paid_date or e.due_date, e.document_no or "", e.description or "",
                   " ".join((e.notes or "").split()))    # o recibo tem uma linha só
