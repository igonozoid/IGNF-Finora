"""Produtos e estoque (módulo "stock"): itens, locais e movimentos.

Regras:
- O saldo e o custo médio nunca ficam gravados: saem dos movimentos (StockMove), na ordem da data. Assim corrigir
  ou excluir um movimento antigo acerta tudo o que vem depois.
- Custo médio ponderado: cada entrada com custo recalcula a média; saídas, perdas e ajustes saem pela média.
- Entrada de compra pode gerar o lançamento a pagar (ligado ao movimento).
- Saída maior que o saldo do local é recusada (inventário corrige diferenças).
- Período fechado (Fechamento de período) também trava movimentos de estoque com data até o fechamento.
"""
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core.money import CENT
from finora.models import Contact, Item, StockLocation, StockMove

KINDS = {"product": "Produto para venda", "input": "Insumo / matéria-prima", "material": "Material de uso interno",
         "produced": "Produzido aqui"}
UNITS = ["un", "kg", "g", "t", "L", "mL", "cx", "pct", "dz", "garrafa", "pote", "saco", "fardo", "m", "m²", "m³",
         "cabeça"]
MOVES = {"in": "Entrada", "out": "Saída / consumo", "loss": "Perda", "adjust": "Inventário (ajuste)",
         "transfer": "Transferência", "sale": "Venda", "prod_in": "Produção (entrou)", "prod_out": "Produção (usou)",
         "farm_out": "Usado na lavoura", "harvest": "Colheita", "herd_out": "Usado no rebanho"}
OUT_KINDS = {"out", "loss", "sale", "prod_out", "farm_out", "herd_out"}
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")
ZERO = Decimal("0")


def qty(v) -> Decimal:
    return Decimal(v).quantize(Q3, rounding=ROUND_HALF_UP)


def fmt_qty(v: Decimal, unit: str = "") -> str:
    """1234.500 -> '1.234,5' (sem zeros à direita)."""
    v = Decimal(v).quantize(Q3)
    text = f"{v:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")
    return f"{text} {unit}".strip() if unit else text


# ---------- locais ----------
def default_location(s: Session, entity_id: int) -> int:
    loc = s.scalars(select(StockLocation).where(StockLocation.entity_id == entity_id, StockLocation.is_active)
                    .order_by(StockLocation.id).limit(1)).first()
    if loc is None:
        loc = StockLocation(entity_id=entity_id, name="Principal", is_active=True)
        s.add(loc)
        s.flush()
    return loc.id


@dataclass(frozen=True)
class LocationView:
    id: int
    name: str
    is_active: bool


def locations(s: Session, entity_id: int, include_inactive: bool = False) -> list[LocationView]:
    default_location(s, entity_id)
    s.commit()                                 # o "Principal" criado agora fica gravado
    q = select(StockLocation).where(StockLocation.entity_id == entity_id)
    if not include_inactive:
        q = q.where(StockLocation.is_active)
    return [LocationView(loc.id, loc.name, loc.is_active) for loc in s.scalars(q.order_by(StockLocation.id))]


def save_location(s: Session, entity_id: int, name: str, location_id: int | None = None,
                  is_active: bool = True) -> int:
    name = " ".join((name or "").split())
    if not name or len(name) > 80:
        raise ValueError("Dê um nome ao local (até 80 letras). Ex.: Depósito, Galpão, Almoxarifado.")
    dup = s.scalar(select(StockLocation.id).where(StockLocation.entity_id == entity_id,
                                                  func.lower(StockLocation.name) == name.lower(),
                                                  StockLocation.id != (location_id or 0)))
    if dup:
        raise ValueError("Já existe um local com esse nome.")
    if location_id is None:
        default_location(s, entity_id)                   # o "Principal" existe antes dos outros
        loc = StockLocation(entity_id=entity_id, name=name, is_active=True)
        s.add(loc)
    else:
        loc = s.get(StockLocation, location_id)
        if not is_active and loc.is_active:
            left = _replay(s, entity_id, location_id=location_id)
            if any(b != 0 for b, _c in left.values()):
                raise ValueError("Esse local ainda tem itens com saldo. Transfira ou ajuste antes de inativar.")
            if len(locations(s, entity_id)) <= 1:
                raise ValueError("Precisa ficar pelo menos um local ativo.")
        loc.name, loc.is_active = name, is_active
    s.commit()
    return loc.id


# ---------- itens ----------
@dataclass(frozen=True)
class ItemView:
    id: int
    code: str
    name: str
    kind: str
    unit: str
    sale_price: Decimal | None
    min_stock: Decimal | None
    category_id: int | None
    notes: str
    is_active: bool
    balance: Decimal = ZERO
    avg_cost: Decimal = ZERO

    @property
    def value(self) -> Decimal:
        return (self.balance * self.avg_cost).quantize(CENT, rounding=ROUND_HALF_UP) if self.balance > 0 else ZERO

    @property
    def below_min(self) -> bool:
        return self.min_stock is not None and self.is_active and self.balance < self.min_stock

    @property
    def kind_label(self) -> str:
        return KINDS.get(self.kind, self.kind)


def _check_item(s: Session, entity_id: int, name: str, kind: str, unit: str, code: str | None,
                exclude_id: int | None = None) -> tuple[str, str | None, str]:
    name = " ".join((name or "").split())
    code = (code or "").strip() or None
    unit = (unit or "").strip()
    if not name:
        raise ValueError("Dê um nome ao item.")
    if len(name) > 120:
        raise ValueError("Nome longo demais (até 120 letras).")
    if kind not in KINDS:
        raise ValueError("Tipo de item inválido.")
    if not unit or len(unit) > 10:
        raise ValueError("Escolha a unidade (un, kg, L…).")
    q = select(Item.id).where(Item.entity_id == entity_id, Item.id != (exclude_id or 0))
    if s.scalar(q.where(func.lower(Item.name) == name.lower())):
        raise ValueError(f"Já existe um item chamado \"{name}\".")
    if code and s.scalar(q.where(Item.code == code)):
        raise ValueError(f"O código {code} já é de outro item.")
    return name, code, unit


def _money(v) -> Decimal | None:
    if v is None or v == "":
        return None
    v = Decimal(v)
    if v < 0:
        raise ValueError("Valores não podem ser negativos.")
    return v


def create_item(s: Session, entity_id: int, *, name: str, kind: str = "product", unit: str = "un",
                code: str | None = None, sale_price=None, min_stock=None, category_id: int | None = None,
                notes: str = "") -> int:
    name, code, unit = _check_item(s, entity_id, name, kind, unit, code)
    it = Item(entity_id=entity_id, name=name, kind=kind, unit=unit, code=code,
              sale_price=_money(sale_price), min_stock=_money(min_stock), category_id=category_id,
              notes=(notes or "").strip()[:300] or None, is_active=True)
    s.add(it)
    s.commit()
    return it.id


def update_item(s: Session, item_id: int, *, name: str, kind: str, unit: str, code: str | None = None,
                sale_price=None, min_stock=None, category_id: int | None = None, notes: str = "",
                is_active: bool = True) -> None:
    it = s.get(Item, item_id)
    it.name, it.code, it.unit = _check_item(s, it.entity_id, name, kind, unit, code, exclude_id=item_id)
    it.kind, it.sale_price, it.min_stock = kind, _money(sale_price), _money(min_stock)
    it.category_id, it.notes, it.is_active = category_id, (notes or "").strip()[:300] or None, is_active
    s.commit()


def _replay(s: Session, entity_id: int, item_ids=None, until: date | None = None,
            location_id: int | None = None) -> dict[int, tuple[Decimal, Decimal]]:
    """item -> (saldo, custo médio). Saldo do local se `location_id`; custo médio é sempre do item todo."""
    q = select(StockMove).where(StockMove.entity_id == entity_id)
    if item_ids is not None:
        q = q.where(StockMove.item_id.in_(list(item_ids)))
    if until is not None:
        q = q.where(StockMove.day <= until)
    total: dict[int, Decimal] = {}
    here: dict[int, Decimal] = {}
    avg: dict[int, Decimal] = {}
    for m in s.scalars(q.order_by(StockMove.day, StockMove.id)):
        q_all, a = total.get(m.item_id, ZERO), avg.get(m.item_id, ZERO)
        mq = Decimal(m.quantity)
        if mq > 0 and m.unit_cost is not None and m.kind != "transfer":
            base = max(q_all, ZERO)
            new_q = base + mq
            a = ((base * a + mq * Decimal(m.unit_cost)) / new_q) if new_q > 0 else Decimal(m.unit_cost)
            avg[m.item_id] = a.quantize(Q4, rounding=ROUND_HALF_UP)
        total[m.item_id] = q_all + mq
        if location_id is None or m.location_id == location_id:
            here[m.item_id] = here.get(m.item_id, ZERO) + mq
    keys = set(total) | set(here)
    return {k: (qty(here.get(k, ZERO)), avg.get(k, ZERO)) for k in keys}


def list_items(s: Session, entity_id: int, search: str = "", kind: str | None = None,
               include_inactive: bool = False, location_id: int | None = None) -> list[ItemView]:
    q = select(Item).where(Item.entity_id == entity_id)
    if not include_inactive:
        q = q.where(Item.is_active)
    if kind:
        q = q.where(Item.kind == kind)
    if search.strip():
        like = f"%{search.strip().lower()}%"
        q = q.where(func.lower(Item.name).like(like) | func.lower(func.coalesce(Item.code, "")).like(like))
    items = list(s.scalars(q.order_by(func.lower(Item.name))))
    bal = _replay(s, entity_id, [i.id for i in items], location_id=location_id) if items else {}
    return [ItemView(i.id, i.code or "", i.name, i.kind, i.unit, i.sale_price, i.min_stock, i.category_id,
                     i.notes or "", i.is_active, *bal.get(i.id, (ZERO, ZERO))) for i in items]


def get_item(s: Session, item_id: int) -> ItemView:
    it = s.get(Item, item_id)
    if it is None:
        raise ValueError("Item não encontrado.")
    return next(v for v in list_items(s, it.entity_id, include_inactive=True) if v.id == item_id)


def low_stock(s: Session, entity_id: int) -> list[ItemView]:
    return [i for i in list_items(s, entity_id) if i.below_min]


# ---------- movimentos ----------
def _check_day(s: Session, entity_id: int, day: date) -> None:
    from finora.services import period_lock
    if period_lock.is_locked(s, entity_id, day):
        lock = period_lock.locked_through(s, entity_id)
        raise ValueError(f"O período até {lock:%d/%m/%Y} está fechado: movimentos de estoque dessa época não "
                         "podem ser criados, alterados nem excluídos.")


def _item(s: Session, entity_id: int, item_id: int) -> Item:
    it = s.get(Item, item_id)
    if it is None or it.entity_id != entity_id:
        raise ValueError("Escolha o item.")
    return it


def _loc(s: Session, entity_id: int, location_id: int | None) -> int:
    if location_id is None:
        return default_location(s, entity_id)
    loc = s.get(StockLocation, location_id)
    if loc is None or loc.entity_id != entity_id:
        raise ValueError("Local inválido.")
    return loc.id


def _positive(quantity) -> Decimal:
    try:
        q = qty(quantity)
    except Exception:
        raise ValueError("Quantidade inválida.")
    if q <= 0:
        raise ValueError("Informe uma quantidade maior que zero.")
    return q


def balance(s: Session, entity_id: int, item_id: int, location_id: int | None = None) -> Decimal:
    return _replay(s, entity_id, [item_id], location_id=location_id).get(item_id, (ZERO, ZERO))[0]


def average_cost(s: Session, entity_id: int, item_id: int, until: date | None = None) -> Decimal:
    return _replay(s, entity_id, [item_id], until=until).get(item_id, (ZERO, ZERO))[1]


def move(s: Session, entity_id: int, *, item_id: int, kind: str, quantity, day: date,
         location_id: int | None = None, unit_cost=None, contact: str | None = None,
         document_no: str | None = None, notes: str | None = None, payable: dict | None = None,
         commit: bool = True) -> int:
    """Entrada (in), saída/consumo (out) ou perda (loss); venda e produção usam os mesmos movimentos.
    `payable` (só entrada): {"account_id", "due_date", "category_id", "paid"} gera o lançamento a pagar da compra."""
    if kind not in MOVES or kind in ("adjust", "transfer"):
        raise ValueError("Tipo de movimento inválido.")
    it = _item(s, entity_id, item_id)
    loc = _loc(s, entity_id, location_id)
    q = _positive(quantity)
    _check_day(s, entity_id, day)
    cost = None
    if kind in ("in", "prod_in"):
        cost = _money(unit_cost)
        if kind == "in" and cost is None:
            raise ValueError("Informe o custo unitário da entrada (pode ser zero, se foi doação).")
    if kind in OUT_KINDS:
        have = balance(s, entity_id, item_id, loc)
        if q > have:
            raise ValueError(f"Saldo insuficiente de {it.name} nesse local: há {fmt_qty(have, it.unit)}. "
                             "Se a contagem física for diferente, faça um inventário.")
    contact_id = None
    if contact and contact.strip():
        from finora.services import contacts
        contact_id = contacts.get_or_create(s, entity_id, contact,
                                            "expense" if kind == "in" else "income" if kind == "sale" else None)
    m = StockMove(entity_id=entity_id, item_id=item_id, location_id=loc, day=day, kind=kind,
                  quantity=q if kind in ("in", "prod_in") else -q,
                  unit_cost=cost.quantize(Q4) if cost is not None else None, contact_id=contact_id,
                  document_no=(document_no or "").strip()[:40] or None, notes=(notes or "").strip()[:300] or None)
    s.add(m)
    s.flush()
    if payable and kind == "in" and cost is not None and cost > 0:
        m.entry_id = _purchase_entry(s, entity_id, it, q, cost, day, contact, document_no, payable)
    if commit:
        s.commit()
    return m.id


def _purchase_entry(s: Session, entity_id: int, it: Item, q: Decimal, cost: Decimal, day: date,
                    contact: str | None, document_no: str | None, payable: dict) -> int:
    from finora.services import entries
    from finora.services.entries import EntryData
    total = (q * cost).quantize(CENT, rounding=ROUND_HALF_UP)
    paid = bool(payable.get("paid"))
    due = payable.get("due_date") or day
    ids = entries.create(s, entity_id, EntryData(
        kind="expense", description=f"Compra: {it.name} ({fmt_qty(q, it.unit)})", amount=total, due_date=due,
        account_id=payable["account_id"], category_id=payable.get("category_id") or it.category_id,
        contact=contact or None, paid=paid, paid_date=due if paid else None, document_no=document_no or None))
    return ids[0]


def adjust(s: Session, entity_id: int, *, item_id: int, counted, day: date, location_id: int | None = None,
           notes: str | None = None) -> int:
    """Inventário: informa a quantidade contada; o Finora lança a diferença (sobra ou falta)."""
    it = _item(s, entity_id, item_id)
    loc = _loc(s, entity_id, location_id)
    try:
        counted = qty(counted)
    except Exception:
        raise ValueError("Quantidade inválida.")
    if counted < 0:
        raise ValueError("A contagem não pode ser negativa.")
    _check_day(s, entity_id, day)
    delta = counted - balance(s, entity_id, item_id, loc)
    if delta == 0:
        raise ValueError(f"O saldo de {it.name} já é {fmt_qty(counted, it.unit)}: nada a ajustar.")
    m = StockMove(entity_id=entity_id, item_id=item_id, location_id=loc, day=day, kind="adjust", quantity=delta,
                  notes=(notes or "Inventário").strip()[:300])
    s.add(m)
    s.commit()
    return m.id


def transfer(s: Session, entity_id: int, *, item_id: int, quantity, day: date, from_id: int, to_id: int,
             notes: str | None = None) -> str:
    it = _item(s, entity_id, item_id)
    a, b = _loc(s, entity_id, from_id), _loc(s, entity_id, to_id)
    if a == b:
        raise ValueError("Escolha locais diferentes.")
    q = _positive(quantity)
    _check_day(s, entity_id, day)
    have = balance(s, entity_id, item_id, a)
    if q > have:
        raise ValueError(f"Saldo insuficiente de {it.name} na origem: há {fmt_qty(have, it.unit)}.")
    tid = uuid.uuid4().hex
    for loc, sign in ((a, -1), (b, 1)):
        s.add(StockMove(entity_id=entity_id, item_id=item_id, location_id=loc, day=day, kind="transfer",
                        quantity=sign * q, transfer_id=tid, notes=(notes or "").strip()[:300] or None))
    s.commit()
    return tid


def delete_move(s: Session, move_id: int) -> int | None:
    """Exclui o movimento (a transferência sai inteira). Devolve o lançamento da compra ligado, se houver
    (ele continua lá: a tela pergunta se quer excluí-lo também)."""
    m = s.get(StockMove, move_id)
    if m is None:
        return None
    if m.sale_id is not None:
        raise ValueError("Esse movimento é de um pedido de venda: cancele o pedido em Vendas.")
    if m.production_id is not None:
        raise ValueError("Esse movimento é de um lote de produção: reabra o lote em Produção.")
    if m.herd_event_id is not None:
        raise ValueError("Esse movimento é de um registro do rebanho: altere ou exclua o registro em Pecuária.")
    if m.activity_id is not None:
        raise ValueError("Esse movimento é de uma atividade da lavoura: altere ou exclua a atividade em Agricultura.")
    _check_day(s, m.entity_id, m.day)
    entry_id = m.entry_id
    pair = list(s.scalars(select(StockMove).where(StockMove.transfer_id == m.transfer_id))) if m.transfer_id else [m]
    for x in pair:
        s.delete(x)
    s.commit()
    return entry_id


@dataclass(frozen=True)
class MoveView:
    id: int
    day: date
    kind: str
    quantity: Decimal
    unit_cost: Decimal | None
    location: str
    contact: str
    document_no: str
    notes: str
    balance: Decimal
    entry_id: int | None
    transfer_id: str | None

    @property
    def kind_label(self) -> str:
        return MOVES.get(self.kind, self.kind)


def history(s: Session, entity_id: int, item_id: int, location_id: int | None = None) -> list[MoveView]:
    """Movimentos do item (mais novos primeiro), com o saldo depois de cada um."""
    q = (select(StockMove, StockLocation.name, Contact.name)
         .join(StockLocation, StockLocation.id == StockMove.location_id)
         .outerjoin(Contact, Contact.id == StockMove.contact_id)
         .where(StockMove.entity_id == entity_id, StockMove.item_id == item_id))
    if location_id is not None:
        q = q.where(StockMove.location_id == location_id)
    out, run = [], ZERO
    for m, loc, contact in s.execute(q.order_by(StockMove.day, StockMove.id)):
        run += Decimal(m.quantity)
        out.append(MoveView(m.id, m.day, m.kind, qty(m.quantity), m.unit_cost, loc, contact or "",
                            m.document_no or "", m.notes or "", qty(run), m.entry_id, m.transfer_id))
    return out[::-1]
