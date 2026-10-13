"""Vendas por pedido (módulo "sales").

Fluxo: o pedido nasce como orçamento (dá para mudar à vontade) e, ao confirmar:
- baixa o estoque de cada item (movimento "Venda", pelo custo médio do dia, que fica guardado para a margem);
- venda gera as contas a receber (à vista já recebida, ou em parcelas); doação e bonificação só baixam o estoque.
Cancelar um pedido confirmado devolve o estoque e manda as parcelas para a lixeira (se nenhuma foi recebida).
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core.money import CENT
from finora.models import Contact, Entry, Item, Sale, SaleItem, StockMove

KINDS = {"sale": "Venda", "donation": "Doação", "bonus": "Bonificação"}
STATUS = {"quote": "Orçamento", "confirmed": "Confirmado", "canceled": "Cancelado"}
PAYMENTS = ["Pix", "Boleto", "Cartão de crédito", "Cartão de débito", "Dinheiro", "Transferência",
            "A combinar"]
ZERO = Decimal("0")


@dataclass
class SaleLine:
    item_id: int
    quantity: Decimal
    unit_price: Decimal


@dataclass
class SaleData:
    day: date
    lines: list[SaleLine]
    contact: str = ""
    kind: str = "sale"
    discount: Decimal = ZERO
    freight: Decimal = ZERO
    account_id: int | None = None
    payment: str | None = None
    installments: int = 1
    first_due: date | None = None
    paid_now: bool = False
    location_id: int | None = None
    category_id: int | None = None
    notes: str = ""


def _money(v) -> Decimal:
    return Decimal(v or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def subtotal(lines) -> Decimal:
    return sum((_money(Decimal(ln.quantity) * Decimal(ln.unit_price)) for ln in lines), ZERO)


def total_of(lines, discount, freight) -> Decimal:
    return subtotal(lines) - _money(discount) + _money(freight)


def _validate(s: Session, entity_id: int, d: SaleData) -> None:
    from finora.services import stock
    if d.kind not in KINDS:
        raise ValueError("Tipo de pedido inválido.")
    if not d.lines:
        raise ValueError("Inclua pelo menos um item no pedido.")
    for ln in d.lines:
        it = s.get(Item, ln.item_id)
        if it is None or it.entity_id != entity_id:
            raise ValueError("Item inválido no pedido.")
        if Decimal(ln.quantity) <= 0:
            raise ValueError(f"Quantidade de {it.name} precisa ser maior que zero.")
        if Decimal(ln.unit_price) < 0:
            raise ValueError(f"Preço de {it.name} não pode ser negativo.")
        stock.qty(ln.quantity)
    if _money(d.discount) < 0 or _money(d.freight) < 0:
        raise ValueError("Desconto e frete não podem ser negativos.")
    if d.kind == "sale" and _money(d.discount) > subtotal(d.lines):
        raise ValueError("O desconto é maior que o valor dos itens.")
    if not 1 <= int(d.installments or 1) <= 60:
        raise ValueError("Parcelas: de 1 a 60.")
    if d.paid_now and int(d.installments or 1) > 1:
        raise ValueError("Recebido à vista só vale para pagamento em 1 vez.")


def _next_number(s: Session, entity_id: int) -> int:
    return (s.scalar(select(func.max(Sale.number)).where(Sale.entity_id == entity_id)) or 0) + 1


def save(s: Session, entity_id: int, d: SaleData, sale_id: int | None = None) -> int:
    """Grava o orçamento (novo ou alterado). Pedido confirmado ou cancelado não muda mais."""
    from finora.services import contacts
    _validate(s, entity_id, d)
    if sale_id is None:
        sale = Sale(entity_id=entity_id, number=_next_number(s, entity_id), status="quote")
        s.add(sale)
    else:
        sale = s.get(Sale, sale_id)
        if sale is None or sale.entity_id != entity_id:
            raise ValueError("Pedido não encontrado.")
        if sale.status != "quote":
            raise ValueError("Só dá para alterar orçamentos. Pedido confirmado: cancele e faça outro.")
        for old in s.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id)):
            s.delete(old)
    sale.day, sale.kind = d.day, d.kind
    sale.contact_id = contacts.get_or_create(s, entity_id, d.contact, "income" if d.kind == "sale" else None)
    sale.discount, sale.freight = _money(d.discount), _money(d.freight)
    sale.account_id, sale.payment = d.account_id, (d.payment or None)
    sale.installments, sale.first_due, sale.paid_now = int(d.installments or 1), d.first_due, bool(d.paid_now)
    sale.location_id, sale.category_id = d.location_id, d.category_id
    sale.notes = (d.notes or "").strip()[:300] or None
    s.flush()
    for ln in d.lines:
        s.add(SaleItem(sale_id=sale.id, item_id=ln.item_id, quantity=Decimal(ln.quantity).quantize(Decimal("0.001")),
                       unit_price=_money(ln.unit_price)))
    s.commit()
    return sale.id


def confirm(s: Session, sale_id: int) -> int:
    """Confirma: baixa o estoque e (venda) gera as contas a receber. Devolve quantas parcelas foram criadas."""
    from finora.services import entries, stock
    from finora.services.entries import EntryData
    sale = s.get(Sale, sale_id)
    if sale is None or sale.status != "quote":
        raise ValueError("Só orçamentos podem ser confirmados.")
    lines = list(s.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id)))
    eid = sale.entity_id
    stock._check_day(s, eid, sale.day)
    loc = stock._loc(s, eid, sale.location_id)
    need: dict[int, Decimal] = {}
    for ln in lines:
        need[ln.item_id] = need.get(ln.item_id, ZERO) + Decimal(ln.quantity)
    for item_id, q in need.items():
        have = stock.balance(s, eid, item_id, loc)
        if q > have:
            it = s.get(Item, item_id)
            raise ValueError(f"Estoque insuficiente de {it.name}: o pedido pede {stock.fmt_qty(q, it.unit)} e há "
                             f"{stock.fmt_qty(have, it.unit)} no local.")
    total = total_of(lines, sale.discount, sale.freight)
    if sale.kind == "sale" and total > 0 and sale.account_id is None:
        raise ValueError("Escolha a conta onde a venda vai ser recebida.")
    contact = s.get(Contact, sale.contact_id).name if sale.contact_id else None
    for ln in lines:
        ln.unit_cost = stock.average_cost(s, eid, ln.item_id, until=sale.day)
        s.add(StockMove(entity_id=eid, item_id=ln.item_id, location_id=loc, day=sale.day, kind="sale",
                        quantity=-Decimal(ln.quantity), contact_id=sale.contact_id, sale_id=sale.id,
                        document_no=f"Pedido {sale.number}"))
    sale.status = "confirmed"
    created = 0
    if sale.kind == "sale" and total > 0:
        n = sale.installments or 1
        due = sale.first_due or sale.day
        desc = f"Venda — pedido {sale.number}" + (f" — {contact}" if contact else "")
        ids = entries.create(s, eid, EntryData(
            kind="income", description=desc, amount=total, due_date=due, account_id=sale.account_id,
            category_id=sale.category_id or _default_category(s, sale, lines), contact=contact,
            document_no=f"Pedido {sale.number}", paid=bool(sale.paid_now), paid_date=due if sale.paid_now else None,
            repeat="installments" if n > 1 else "none", times=n))
        series = s.get(Entry, ids[0]).series_id or uuid.uuid4().hex
        for i in ids:
            s.get(Entry, i).series_id = series
        sale.series_id = series
        created = len(ids)
    s.commit()
    return created


def _default_category(s: Session, sale: Sale, lines: list[SaleItem]) -> int | None:
    """Categoria da venda: a do primeiro item que tiver uma de receita."""
    from finora.models import Category
    for ln in lines:
        it = s.get(Item, ln.item_id)
        cat = s.get(Category, it.category_id) if it.category_id else None
        if cat is not None and cat.kind == "income":
            return cat.id
    return None


def _installments(s: Session, sale: Sale) -> list[Entry]:
    if not sale.series_id:
        return []
    return list(s.scalars(select(Entry).where(Entry.series_id == sale.series_id, Entry.entity_id == sale.entity_id)
                          .order_by(Entry.due_date)))


def cancel(s: Session, sale_id: int) -> None:
    from finora.services import stock, trash
    sale = s.get(Sale, sale_id)
    if sale is None or sale.status == "canceled":
        return
    if sale.status == "confirmed":
        stock._check_day(s, sale.entity_id, sale.day)
        parts = _installments(s, sale)
        if any(e.status == "paid" for e in parts):
            raise ValueError("Esse pedido já tem parcela recebida. Desfaça o recebimento em Lançamentos antes de "
                             "cancelar.")
        trash.move(s, parts)
        for m in s.scalars(select(StockMove).where(StockMove.sale_id == sale.id)):
            s.delete(m)
    sale.status = "canceled"
    s.commit()


# ---------- consultas ----------
@dataclass(frozen=True)
class SaleView:
    id: int
    number: int
    day: date
    contact: str
    kind: str
    status: str
    total: Decimal
    received: Decimal
    items: int

    @property
    def kind_label(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def status_label(self) -> str:
        return STATUS.get(self.status, self.status)


def list_sales(s: Session, entity_id: int, first: date | None = None, last: date | None = None,
               status: str | None = None, search: str = "") -> list[SaleView]:
    q = (select(Sale, Contact.name).outerjoin(Contact, Contact.id == Sale.contact_id)
         .where(Sale.entity_id == entity_id))
    if first:
        q = q.where(Sale.day >= first)
    if last:
        q = q.where(Sale.day <= last)
    if status:
        q = q.where(Sale.status == status)
    if search.strip():
        text = search.strip()
        q = q.where(Sale.number == int(text)) if text.isdigit() else             q.where(func.lower(func.coalesce(Contact.name, "")).like(f"%{text.lower()}%"))
    out = []
    for sale, contact in s.execute(q.order_by(Sale.day.desc(), Sale.number.desc())):
        lines = list(s.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id)))
        total = total_of(lines, sale.discount, sale.freight)
        received = sum((Decimal(e.amount) for e in _installments(s, sale) if e.status == "paid"), ZERO)
        out.append(SaleView(sale.id, sale.number, sale.day, contact or "", sale.kind, sale.status, total, received,
                            len(lines)))
    return out


@dataclass
class SaleDetail:
    id: int
    number: int
    status: str
    data: SaleData
    names: dict[int, tuple[str, str]] = field(default_factory=dict)     # item -> (nome, unidade)
    costs: dict[int, Decimal] = field(default_factory=dict)              # linha -> custo unitário (confirmado)
    installments: list = field(default_factory=list)                    # (vencimento, valor, recebido?)

    @property
    def total(self) -> Decimal:
        return total_of(self.data.lines, self.data.discount, self.data.freight)


def get(s: Session, sale_id: int) -> SaleDetail:
    sale = s.get(Sale, sale_id)
    if sale is None:
        raise ValueError("Pedido não encontrado.")
    lines = list(s.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.id)))
    contact = s.get(Contact, sale.contact_id).name if sale.contact_id else ""
    data = SaleData(sale.day, [SaleLine(ln.item_id, Decimal(ln.quantity), Decimal(ln.unit_price)) for ln in lines],
                    contact, sale.kind, Decimal(sale.discount), Decimal(sale.freight), sale.account_id, sale.payment,
                    sale.installments, sale.first_due, sale.paid_now, sale.location_id, sale.category_id,
                    sale.notes or "")
    names = {ln.item_id: (s.get(Item, ln.item_id).name, s.get(Item, ln.item_id).unit) for ln in lines}
    costs = {i: Decimal(ln.unit_cost) for i, ln in enumerate(lines) if ln.unit_cost is not None}
    parts = [(e.due_date, Decimal(e.amount), e.status == "paid") for e in _installments(s, sale)]
    return SaleDetail(sale.id, sale.number, sale.status, data, names, costs, parts)


@dataclass(frozen=True)
class SalesRow:
    name: str
    unit: str
    quantity: Decimal
    revenue: Decimal
    cost: Decimal

    @property
    def margin(self) -> Decimal:
        return self.revenue - self.cost

    @property
    def margin_pct(self) -> Decimal | None:
        return (self.margin * 100 / self.revenue).quantize(Decimal("0.1")) if self.revenue else None


def summary(s: Session, entity_id: int, first: date, last: date, by: str = "item") -> list[SalesRow]:
    """Vendas confirmadas no período, por item ou por cliente: quantidade, receita, custo e margem.
    Doação e bonificação entram com receita zero (aparece o custo)."""
    q = (select(Sale, SaleItem, Item, Contact.name)
         .join(SaleItem, SaleItem.sale_id == Sale.id).join(Item, Item.id == SaleItem.item_id)
         .outerjoin(Contact, Contact.id == Sale.contact_id)
         .where(Sale.entity_id == entity_id, Sale.status == "confirmed", Sale.day.between(first, last)))
    acc: dict[str, list] = {}
    for sale, ln, it, contact in s.execute(q):
        key = it.name if by == "item" else (contact or "(sem cliente)")
        unit = it.unit if by == "item" else ""
        row = acc.setdefault(key, [unit, ZERO, ZERO, ZERO])
        q_ = Decimal(ln.quantity)
        row[1] += q_ if by == "item" else ZERO
        if sale.kind == "sale":
            row[2] += _money(q_ * Decimal(ln.unit_price))
        row[3] += _money(q_ * Decimal(ln.unit_cost or 0))
    # desconto e frete do pedido: entram na receita do cliente (por item, o desconto fica proporcional)
    for sale, contact in s.execute(select(Sale, Contact.name).outerjoin(Contact, Contact.id == Sale.contact_id)
                                   .where(Sale.entity_id == entity_id, Sale.status == "confirmed",
                                          Sale.kind == "sale", Sale.day.between(first, last))):
        adj = Decimal(sale.freight) - Decimal(sale.discount)
        if not adj:
            continue
        if by == "item":
            lines = list(s.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id)))
            sub = subtotal(lines) or Decimal(1)
            for ln in lines:
                name = s.get(Item, ln.item_id).name
                acc[name][2] += _money(adj * _money(Decimal(ln.quantity) * Decimal(ln.unit_price)) / sub)
        else:
            acc[contact or "(sem cliente)"][2] += _money(adj)
    rows = [SalesRow(k, v[0], v[1], v[2], v[3]) for k, v in acc.items()]
    return sorted(rows, key=lambda r: -r.revenue)
