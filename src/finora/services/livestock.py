"""Pecuária por lote (módulo "livestock"): o rebanho é controlado por lote, não por animal.

- Lote (ex.: "Vacas de cria", "Recria 2026") tem espécie, categoria e o piquete onde está (área da Agricultura).
- A contagem de cabeças sai dos registros: nascimento, compra e transferência que entra somam; venda, morte e
  transferência que sai subtraem. Nunca fica gravada (corrigir um registro antigo acerta tudo).
- Compra e venda podem gerar a conta a pagar / a receber (ligada ao registro).
- Sanidade (vacina, remédio) e alimentação (ração, silagem, sal) tiram os insumos do estoque pelo custo médio;
  outros custos (veterinário, frete) entram só no custo do lote.
- Pesagem guarda o peso médio; com duas pesagens, sai o ganho médio por dia (GMD).
- Troca de piquete muda o lugar do lote a partir da data.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core.money import CENT
from finora.models import Contact, Entry, Farm, FarmArea, HerdEvent, HerdLot, Item, StockMove

SPECIES = {"cattle": "Bovinos", "buffalo": "Bubalinos", "sheep": "Ovinos", "goat": "Caprinos", "horse": "Equinos",
           "pig": "Suínos", "poultry": "Aves", "other": "Outros"}
CATEGORIES = ["Vaca", "Novilha", "Bezerra", "Bezerro", "Garrote", "Boi", "Touro", "Matriz", "Reprodutor",
              "Cordeiro", "Leitão", "Misto"]
EVENTS = {"birth": "Nascimento", "purchase": "Compra", "sale": "Venda", "death": "Morte",
          "transfer": "Transferência para outro lote", "move": "Troca de piquete", "weighing": "Pesagem",
          "health": "Sanidade (vacina, remédio)", "feeding": "Alimentação (ração, silagem, sal)",
          "occurrence": "Ocorrência"}
LABELS = {**EVENTS, "transfer_out": "Transferência (saiu)", "transfer_in": "Transferência (entrou)"}
SIGN = {"birth": 1, "purchase": 1, "transfer_in": 1, "sale": -1, "death": -1, "transfer_out": -1}
COUNT_KINDS = {"birth", "purchase", "sale", "death", "transfer"}       # pedem nº de cabeças
ZERO = Decimal("0")
Q3 = Decimal("0.001")


def _money(v) -> Decimal:
    return Decimal(v or 0).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- lotes ----------
@dataclass(frozen=True)
class LotView:
    id: int
    name: str
    species: str
    category: str
    area_id: int | None                   # piquete atual
    area: str
    heads: int
    weight: Decimal | None                # peso médio da última pesagem
    weighed_on: date | None
    daily_gain: Decimal | None            # GMD entre as duas últimas pesagens (kg/dia)
    notes: str
    is_active: bool

    @property
    def species_label(self) -> str:
        return SPECIES.get(self.species, self.species)


def _heads(s: Session, entity_id: int, until: date | None = None, exclude: set[int] | None = None) -> dict[int, int]:
    q = select(HerdEvent.lot_id, func.sum(HerdEvent.heads)).where(HerdEvent.entity_id == entity_id)
    if until is not None:
        q = q.where(HerdEvent.day <= until)
    if exclude:
        q = q.where(HerdEvent.id.not_in(list(exclude)))
    return {lot: int(n or 0) for lot, n in s.execute(q.group_by(HerdEvent.lot_id))}


def heads(s: Session, entity_id: int, lot_id: int, until: date | None = None) -> int:
    return _heads(s, entity_id, until).get(lot_id, 0)


def _area_names(s: Session, entity_id: int) -> dict[int, str]:
    q = (select(FarmArea.id, Farm.name, FarmArea.name).join(Farm, Farm.id == FarmArea.farm_id)
         .where(FarmArea.entity_id == entity_id))
    return {i: f"{f} › {a}" for i, f, a in s.execute(q)}


def lots(s: Session, entity_id: int, include_inactive: bool = False) -> list[LotView]:
    q = select(HerdLot).where(HerdLot.entity_id == entity_id)
    if not include_inactive:
        q = q.where(HerdLot.is_active)
    rows = list(s.scalars(q.order_by(func.lower(HerdLot.name))))
    count = _heads(s, entity_id)
    names = _area_names(s, entity_id)
    where: dict[int, int | None] = {}
    weighs: dict[int, list[tuple[date, Decimal]]] = {}
    evq = (select(HerdEvent).where(HerdEvent.entity_id == entity_id, HerdEvent.kind.in_(("move", "weighing")))
           .order_by(HerdEvent.day, HerdEvent.id))
    for ev in s.scalars(evq):
        if ev.kind == "move":
            where[ev.lot_id] = ev.area_id
        elif ev.weight is not None:
            weighs.setdefault(ev.lot_id, []).append((ev.day, Decimal(ev.weight)))
    out = []
    for lot in rows:
        area_id = where.get(lot.id, lot.area_id)
        w = weighs.get(lot.id, [])
        gain = None
        if len(w) >= 2 and w[-1][0] > w[-2][0]:
            gain = ((w[-1][1] - w[-2][1]) / (w[-1][0] - w[-2][0]).days).quantize(Q3, rounding=ROUND_HALF_UP)
        out.append(LotView(lot.id, lot.name, lot.species, lot.category or "", area_id, names.get(area_id, ""),
                           count.get(lot.id, 0), w[-1][1] if w else None, w[-1][0] if w else None, gain,
                           lot.notes or "", lot.is_active))
    return out


def save_lot(s: Session, entity_id: int, *, name: str, species: str = "cattle", category: str = "",
             area_id: int | None = None, notes: str = "", is_active: bool = True, lot_id: int | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Dê um nome ao lote (ex.: Vacas de cria, Recria 2026).")
    if species not in SPECIES:
        raise ValueError("Espécie inválida.")
    dup = s.scalar(select(HerdLot.id).where(HerdLot.entity_id == entity_id, func.lower(HerdLot.name) == name.lower(),
                                            HerdLot.id != (lot_id or 0)))
    if dup:
        raise ValueError("Já existe um lote com esse nome.")
    if area_id is not None:
        a = s.get(FarmArea, area_id)
        if a is None or a.entity_id != entity_id:
            raise ValueError("Piquete inválido.")
    if lot_id is None:
        lot = HerdLot(entity_id=entity_id)
        s.add(lot)
    else:
        lot = s.get(HerdLot, lot_id)
        if lot is None or lot.entity_id != entity_id:
            raise ValueError("Lote não encontrado.")
        if not is_active and lot.is_active and heads(s, entity_id, lot.id):
            raise ValueError("O lote ainda tem animais. Transfira, venda ou registre as saídas antes de inativar.")
    lot.name, lot.species, lot.category = name[:80], species, (category or "").strip()[:40] or None
    lot.area_id, lot.notes, lot.is_active = area_id, (notes or "").strip()[:300] or None, is_active
    s.commit()
    return lot.id


# ---------- registros ----------
@dataclass
class Use:
    item_id: int
    quantity: Decimal


@dataclass
class EventData:
    lot_id: int
    day: date
    kind: str
    heads: int = 0                        # sempre positivo; o sinal vem do tipo
    weight: Decimal | None = None         # peso médio por cabeça (kg)
    value: Decimal = ZERO                 # valor total da compra/venda
    other_cost: Decimal = ZERO
    inputs: list[Use] = field(default_factory=list)
    area_id: int | None = None            # troca de piquete: para onde foi
    to_lot_id: int | None = None          # transferência: lote de destino
    contact: str = ""
    finance: dict | None = None           # {"account_id", "due_date", "category_id", "paid"}: gera a pagar/receber
    description: str = ""
    notes: str = ""
    location_id: int | None = None


def _lot(s: Session, entity_id: int, lot_id: int | None) -> HerdLot:
    lot = s.get(HerdLot, lot_id) if lot_id else None
    if lot is None or lot.entity_id != entity_id:
        raise ValueError("Escolha o lote.")
    return lot


def _validate(s: Session, entity_id: int, d: EventData, exclude: set[int]) -> None:
    from finora.services import stock
    lot = _lot(s, entity_id, d.lot_id)
    if d.kind not in EVENTS:
        raise ValueError("Tipo de registro inválido.")
    n = int(d.heads or 0)
    if n < 0:
        raise ValueError("Número de cabeças não pode ser negativo.")
    if d.kind in COUNT_KINDS and n <= 0:
        raise ValueError("Informe quantas cabeças.")
    if d.kind in ("sale", "death", "transfer"):
        have = _heads(s, entity_id, d.day, exclude).get(lot.id, 0)
        if n > have:
            raise ValueError(f"O lote {lot.name} tem {have} cabeça(s) nessa data; não dá para tirar {n}.")
    if d.kind == "transfer":
        dest = _lot(s, entity_id, d.to_lot_id)
        if dest.id == lot.id:
            raise ValueError("Escolha outro lote de destino.")
    if d.kind == "move":
        a = s.get(FarmArea, d.area_id) if d.area_id else None
        if a is None or a.entity_id != entity_id:
            raise ValueError("Escolha o piquete de destino.")
    if d.kind == "weighing" and (d.weight is None or Decimal(d.weight) <= 0):
        raise ValueError("Informe o peso médio (kg por cabeça).")
    if d.weight is not None and Decimal(d.weight) < 0:
        raise ValueError("Peso não pode ser negativo.")
    if _money(d.value) < 0 or _money(d.other_cost) < 0:
        raise ValueError("Valores não podem ser negativos.")
    if d.finance and d.kind in ("purchase", "sale") and _money(d.value) > 0 and not d.finance.get("account_id"):
        raise ValueError("Escolha a conta do pagamento.")
    for u in d.inputs:
        it = s.get(Item, u.item_id)
        if it is None or it.entity_id != entity_id:
            raise ValueError("Item inválido.")
        if Decimal(u.quantity) <= 0:
            raise ValueError(f"Quantidade de {it.name} precisa ser maior que zero.")
        stock.qty(u.quantity)


def _undo(s: Session, ev: HerdEvent) -> None:
    """Desfaz um registro (e o par da transferência): insumos voltam, a conta vai para a lixeira."""
    from finora.services import stock, trash
    group = list(s.scalars(select(HerdEvent).where(HerdEvent.transfer_id == ev.transfer_id))) if ev.transfer_id \
        else [ev]
    for e in group:
        stock._check_day(s, e.entity_id, e.day)
        if e.entry_id:
            entry = s.get(Entry, e.entry_id)
            if entry is not None and entry.deleted_at is None:
                if entry.status == "paid":
                    raise ValueError("A conta desse registro já foi paga/recebida. Desfaça o pagamento em "
                                     "Lançamentos antes de alterar ou excluir.")
                trash.move(s, [entry])
    for e in group:
        for m in s.scalars(select(StockMove).where(StockMove.herd_event_id == e.id)):
            s.delete(m)
        s.delete(e)
    s.flush()


def save_event(s: Session, entity_id: int, d: EventData, event_id: int | None = None) -> int:
    """Grava o registro (alterar = desfazer o antigo e gravar de novo). Devolve o id do registro do lote."""
    from finora.services import contacts, entries, stock
    from finora.services.entries import EntryData
    old = None
    exclude: set[int] = set()
    if event_id is not None:
        old = s.get(HerdEvent, event_id)
        if old is None or old.entity_id != entity_id:
            raise ValueError("Registro não encontrado.")
        exclude = {e.id for e in s.scalars(select(HerdEvent).where(HerdEvent.transfer_id == old.transfer_id))} \
            if old.transfer_id else {old.id}
    _validate(s, entity_id, d, exclude)
    stock._check_day(s, entity_id, d.day)
    loc = stock._loc(s, entity_id, d.location_id)
    need: dict[int, Decimal] = {}
    for u in d.inputs:
        need[u.item_id] = need.get(u.item_id, ZERO) + Decimal(u.quantity)
    if old is not None:
        _undo(s, old)
    for item_id, q in need.items():
        have = stock.balance(s, entity_id, item_id, loc)
        if q > have:
            it = s.get(Item, item_id)
            s.rollback()
            raise ValueError(f"Falta {it.name} no estoque: o registro usa {stock.fmt_qty(q, it.unit)} e há "
                             f"{stock.fmt_qty(have, it.unit)} no local. Lance a entrada antes.")
    lot = s.get(HerdLot, d.lot_id)
    n = int(d.heads or 0)
    kind = "transfer_out" if d.kind == "transfer" else d.kind
    contact_id = contacts.get_or_create(s, entity_id, d.contact, "expense" if d.kind == "purchase" else
                                        "income" if d.kind == "sale" else None) if d.contact.strip() else None
    ev = HerdEvent(entity_id=entity_id, lot_id=lot.id, day=d.day, kind=kind, heads=SIGN.get(kind, 0) * n,
                   weight=Decimal(d.weight).quantize(Q3) if d.weight is not None else None, value=_money(d.value),
                   other_cost=_money(d.other_cost), inputs_cost=ZERO,
                   area_id=d.area_id if d.kind == "move" else None,
                   other_lot_id=d.to_lot_id if d.kind == "transfer" else None, contact_id=contact_id,
                   location_id=d.location_id, description=(d.description or "").strip()[:200] or None,
                   notes=(d.notes or "").strip()[:300] or None)
    s.add(ev)
    s.flush()
    if d.kind == "transfer":
        ev.transfer_id = uuid.uuid4().hex
        s.add(HerdEvent(entity_id=entity_id, lot_id=d.to_lot_id, day=d.day, kind="transfer_in", heads=n,
                        weight=ev.weight, value=ZERO, other_cost=ZERO, inputs_cost=ZERO, other_lot_id=lot.id,
                        transfer_id=ev.transfer_id, description=ev.description))
    used = ZERO
    note = f"Rebanho: {lot.name} — {EVENTS[d.kind]}"
    for u in d.inputs:
        avg = stock.average_cost(s, entity_id, u.item_id, until=d.day)
        used += Decimal(u.quantity) * avg
        s.add(StockMove(entity_id=entity_id, item_id=u.item_id, location_id=loc, day=d.day, kind="herd_out",
                        quantity=-stock.qty(u.quantity), unit_cost=avg.quantize(Decimal("0.0001")),
                        herd_event_id=ev.id, notes=note[:300]))
    ev.inputs_cost = _money(used)
    s.flush()
    if d.finance and d.kind in ("purchase", "sale") and _money(d.value) > 0:
        f = d.finance
        paid = bool(f.get("paid"))
        due = f.get("due_date") or d.day
        what = "Compra" if d.kind == "purchase" else "Venda"
        ids = entries.create(s, entity_id, EntryData(
            kind="expense" if d.kind == "purchase" else "income",
            description=f"{what} de animais: {n} cab. ({lot.name})", amount=_money(d.value), due_date=due,
            account_id=f["account_id"], category_id=f.get("category_id"), contact=d.contact or None, paid=paid,
            paid_date=due if paid else None))
        ev = s.get(HerdEvent, ev.id)
        ev.entry_id = ids[0]
    s.commit()
    return ev.id


def delete_event(s: Session, event_id: int) -> None:
    ev = s.get(HerdEvent, event_id)
    if ev is None:
        return
    lot_heads = _heads(s, ev.entity_id, exclude={e.id for e in (
        s.scalars(select(HerdEvent).where(HerdEvent.transfer_id == ev.transfer_id)) if ev.transfer_id else [ev])})
    if any(n < 0 for n in lot_heads.values()):
        raise ValueError("Sem esse registro, algum lote ficaria com cabeças negativas (já saíram animais depois). "
                         "Exclua os registros de saída antes.")
    _undo(s, ev)
    s.commit()


# ---------- consultas ----------
@dataclass(frozen=True)
class EventView:
    id: int
    day: date
    lot_id: int
    lot: str
    kind: str
    heads: int
    weight: Decimal | None
    value: Decimal
    inputs_cost: Decimal
    other_cost: Decimal
    area: str
    other_lot: str
    contact: str
    description: str
    notes: str
    inputs: str
    entry_id: int | None
    transfer_id: str | None
    location_id: int | None

    @property
    def kind_label(self) -> str:
        return LABELS.get(self.kind, self.kind)

    @property
    def cost(self) -> Decimal:
        return self.inputs_cost + self.other_cost

    @property
    def detail(self) -> str:
        """Resumo do que aconteceu: piquete novo, lote de destino, peso, insumos…"""
        from finora.services import stock
        bits = []
        if self.kind == "move" and self.area:
            bits.append(f"para {self.area}")
        if self.kind == "transfer_out":
            bits.append(f"para {self.other_lot}")
        if self.kind == "transfer_in":
            bits.append(f"de {self.other_lot}")
        if self.weight is not None:
            bits.append(f"{stock.fmt_qty(self.weight)} kg/cab.")
        if self.inputs:
            bits.append(self.inputs)
        if self.contact:
            bits.append(self.contact)
        if self.description:
            bits.append(self.description)
        return " · ".join(bits)


def list_events(s: Session, entity_id: int, first: date | None = None, last: date | None = None,
                lot_id: int | None = None, kind: str | None = None) -> list[EventView]:
    from finora.services import stock
    q = (select(HerdEvent, HerdLot.name, Contact.name).join(HerdLot, HerdLot.id == HerdEvent.lot_id)
         .outerjoin(Contact, Contact.id == HerdEvent.contact_id).where(HerdEvent.entity_id == entity_id))
    if first is not None:
        q = q.where(HerdEvent.day >= first)
    if last is not None:
        q = q.where(HerdEvent.day <= last)
    if lot_id is not None:
        q = q.where(HerdEvent.lot_id == lot_id)
    if kind:
        q = q.where(HerdEvent.kind.in_(("transfer_out", "transfer_in")) if kind == "transfer" else
                    HerdEvent.kind == kind)
    rows = list(s.execute(q.order_by(HerdEvent.day.desc(), HerdEvent.id.desc())))
    ids = [e.id for e, _l, _c in rows]
    uses: dict[int, list[str]] = {}
    if ids:
        mq = (select(StockMove, Item.name, Item.unit).join(Item, Item.id == StockMove.item_id)
              .where(StockMove.herd_event_id.in_(ids)).order_by(StockMove.id))
        for m, name, unit in s.execute(mq):
            uses.setdefault(m.herd_event_id, []).append(f"{name} {stock.fmt_qty(abs(Decimal(m.quantity)), unit)}")
    names = _area_names(s, entity_id)
    lot_names = dict(s.execute(select(HerdLot.id, HerdLot.name).where(HerdLot.entity_id == entity_id)).all())
    return [EventView(e.id, e.day, e.lot_id, lot, e.kind, e.heads, e.weight, Decimal(e.value), Decimal(e.inputs_cost),
                      Decimal(e.other_cost), names.get(e.area_id, ""), lot_names.get(e.other_lot_id, ""),
                      contact or "", e.description or "", e.notes or "", ", ".join(uses.get(e.id, [])), e.entry_id,
                      e.transfer_id, e.location_id) for e, lot, contact in rows]


@dataclass(frozen=True)
class EventDetail:
    view: EventView
    inputs: list[tuple[int, Decimal]]     # (item, quantidade)
    finance: dict | None                  # o que gerou a conta (para editar)


def get_event(s: Session, event_id: int) -> EventDetail:
    ev = s.get(HerdEvent, event_id)
    if ev is None:
        raise ValueError("Registro não encontrado.")
    if ev.kind == "transfer_in":                      # a transferência se edita pelo lado que saiu
        ev = s.scalars(select(HerdEvent).where(HerdEvent.transfer_id == ev.transfer_id,
                                               HerdEvent.kind == "transfer_out")).first() or ev
    view = next(v for v in list_events(s, ev.entity_id, ev.day, ev.day, lot_id=ev.lot_id) if v.id == ev.id)
    ins = [(m.item_id, abs(Decimal(m.quantity))) for m in
           s.scalars(select(StockMove).where(StockMove.herd_event_id == ev.id).order_by(StockMove.id))]
    fin = None
    if ev.entry_id:
        e = s.get(Entry, ev.entry_id)
        if e is not None:
            fin = {"account_id": e.account_id, "due_date": e.due_date, "category_id": e.category_id,
                   "paid": e.status == "paid"}
    return EventDetail(view, ins, fin)


@dataclass(frozen=True)
class LotCostRow:
    lot_id: int
    lot: str
    heads: int                            # cabeças hoje
    births: int
    deaths: int
    bought: int
    sold: int
    purchases: Decimal
    sales: Decimal
    inputs_cost: Decimal
    other_cost: Decimal

    @property
    def cost(self) -> Decimal:
        return self.inputs_cost + self.other_cost

    @property
    def per_head(self) -> Decimal | None:
        return _money(self.cost / self.heads) if self.heads > 0 else None


def lot_costs(s: Session, entity_id: int, first: date, last: date) -> list[LotCostRow]:
    """Por lote, no período: nascimentos, mortes, compras e vendas (cabeças e valor) e o custo de manutenção
    (sanidade, alimentação e outros custos)."""
    now = {lv.id: lv for lv in lots(s, entity_id, include_inactive=True)}
    acc: dict[int, dict] = {}
    for e in list_events(s, entity_id, first, last):
        r = acc.setdefault(e.lot_id, {"b": 0, "d": 0, "pb": 0, "sd": 0, "p": ZERO, "s": ZERO, "i": ZERO, "o": ZERO})
        if e.kind == "birth":
            r["b"] += e.heads
        elif e.kind == "death":
            r["d"] += -e.heads
        elif e.kind == "purchase":
            r["pb"] += e.heads
            r["p"] += e.value
        elif e.kind == "sale":
            r["sd"] += -e.heads
            r["s"] += e.value
        r["i"] += e.inputs_cost
        r["o"] += e.other_cost
    out = [LotCostRow(lid, now[lid].name if lid in now else "?", now[lid].heads if lid in now else 0, r["b"], r["d"],
                      r["pb"], r["sd"], _money(r["p"]), _money(r["s"]), _money(r["i"]), _money(r["o"]))
           for lid, r in acc.items()]
    return sorted(out, key=lambda r: r.lot.lower())
