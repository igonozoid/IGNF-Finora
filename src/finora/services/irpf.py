"""Ajuda para a declaração do Imposto de Renda (IRPF): o que o Finora sabe do ano, no formato que a declaração pede.

- Rendimentos recebidos, por fonte pagadora (contato) com CPF/CNPJ — pela data do recebimento.
- Pagamentos de saúde e educação (grupos da DRE), por quem recebeu, com CPF/CNPJ — pela data do pagamento.
  São os que costumam ser dedutíveis; a regra de cada gasto (remédio não deduz, educação tem limite) é da Receita.
- Saldo das contas em 31/12 do ano anterior e do ano (Bens e Direitos).

O Finora não preenche a declaração: é um resumo para conferir e digitar no programa da Receita.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finora.core import documents
from finora.core.money import CENT
from finora.models import Account, Category, Contact, Entry

ZERO = Decimal("0.00")
DEDUCTIBLE = {"saude": "Saúde", "educacao": "Educação"}
NO_CONTACT = "(sem contato informado)"


@dataclass(frozen=True)
class IrRow:
    name: str
    document: str            # CPF/CNPJ formatado ("" = falta)
    previous: Decimal        # ano anterior (comparação) ou saldo em 31/12 do ano anterior
    value: Decimal           # o ano da declaração ou saldo em 31/12
    count: int = 0

    @property
    def missing_doc(self) -> bool:
        return not self.document and self.name != NO_CONTACT


@dataclass
class IrReport:
    year: int
    incomes: list[IrRow] = field(default_factory=list)
    deductible: dict[str, list[IrRow]] = field(default_factory=dict)     # "saude"/"educacao" -> linhas
    balances: list[IrRow] = field(default_factory=list)
    currency_note: str = ""

    def total(self, rows: list[IrRow]) -> tuple[Decimal, Decimal]:
        return sum((r.previous for r in rows), ZERO), sum((r.value for r in rows), ZERO)

    @property
    def missing(self) -> int:
        """Quantas linhas de rendimento/pagamento estão sem CPF/CNPJ ou sem contato."""
        rows = self.incomes + [r for g in self.deductible.values() for r in g]
        return sum(1 for r in rows if r.missing_doc or r.name == NO_CONTACT)


def _groups(s: Session, entity_id: int) -> dict[int, str]:
    """categoria -> grupo da DRE (subcategoria herda do grupo)."""
    cats = {c.id: c for c in s.scalars(select(Category))}
    out = {}
    for cid, c in cats.items():
        parent = cats.get(c.parent_id) if c.parent_id else None
        out[cid] = c.dre_group or (parent.dre_group if parent else None) or ""
    return out


def _by_contact(s: Session, entity_id: int, year: int, kind: str, cat_ok) -> list[IrRow]:
    first, last = date(year - 1, 1, 1), date(year, 12, 31)
    q = (select(Entry.paid_date, Entry.base_amount, Entry.category_id, Contact.id, Contact.name, Contact.document)
         .outerjoin(Contact, Contact.id == Entry.contact_id)
         .where(Entry.entity_id == entity_id, Entry.kind == kind, Entry.status.in_(("paid", "card")),
                Entry.paid_date.between(first, last)))
    sums: dict = defaultdict(lambda: [ZERO, ZERO, 0])
    names: dict = {}
    for when, amount, cat_id, cid, name, doc in s.execute(q):
        if not cat_ok(cat_id):
            continue
        key = cid or 0
        names[key] = (name or NO_CONTACT, documents.fmt(doc) if doc else "")
        acc = sums[key]
        if when.year == year:
            acc[1] += Decimal(amount)
            acc[2] += 1
        else:
            acc[0] += Decimal(amount)
    rows = [IrRow(names[k][0], names[k][1], v[0].quantize(CENT), v[1].quantize(CENT), v[2])
            for k, v in sums.items() if v[1]]          # só quem aparece no ano da declaração
    return sorted(rows, key=lambda r: (r.name == NO_CONTACT, -r.value))


def report(s: Session, entity_id: int, year: int) -> IrReport:
    from finora.services import fx, reports
    rep = IrReport(year)
    groups = _groups(s, entity_id)
    rep.incomes = _by_contact(s, entity_id, year, "income", lambda _c: True)
    for key in DEDUCTIBLE:
        rep.deductible[key] = _by_contact(s, entity_id, year, "expense", lambda c, k=key: groups.get(c) == k)
    conv = fx.Converter(s, entity_id)
    ends = (date(year - 1, 12, 31), date(year, 12, 31))
    for acc in s.scalars(select(Account).where(Account.entity_id == entity_id, Account.kind != "card")
                         .order_by(Account.name)):
        vals = []
        for end in ends:
            bal = reports.account_statement(s, acc.id, end, end).closing
            vals.append(bal if acc.currency == conv.base else conv.convert(bal, acc.currency, end))
        if any(vals):
            name = acc.name + ("" if acc.currency == conv.base else f" ({acc.currency}, convertido)")
            rep.balances.append(IrRow(name, "", vals[0].quantize(CENT), vals[1].quantize(CENT)))
    return rep
