"""Produção por lote (módulo "production"): insumos que saem do estoque viram produtos que entram.

Fluxo: o lote nasce "em andamento" (dá para mudar à vontade, não mexe no estoque). Ao concluir:
- cada insumo sai do estoque (movimento "Produção (usou)") pelo custo médio do dia, que fica guardado;
- custo do lote = insumos + outros custos (mão de obra, energia, embalagem que não está no estoque…);
- cada produto entra no estoque ("Produção (entrou)") com o custo por unidade. Com mais de um produto, o custo se
  divide pelo % informado em cada um ou, sem %, proporcional à quantidade.
Reabrir um lote concluído desfaz os movimentos (se os produtos ainda estiverem no estoque).
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core.money import CENT
from finora.models import Item, Production, ProductionLine, StockMove

STATUS = {"open": "Em andamento", "done": "Concluído"}
ZERO = Decimal("0")
HUNDRED = Decimal("100")
Q4 = Decimal("0.0001")


@dataclass
class Line:
    item_id: int
    quantity: Decimal
    share: Decimal | None = None          # só nos produtos (% do custo)


@dataclass
class ProductionData:
    name: str
    day: date
    inputs: list[Line]
    outputs: list[Line]
    extra_cost: Decimal = ZERO
    location_id: int | None = None
    notes: str = ""


def _money(v) -> Decimal:
    return Decimal(v or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def split_costs(total: Decimal, outputs: list[Line]) -> list[Decimal]:
    """Custo por unidade de cada produto. Sem % informado: proporcional à quantidade."""
    if not outputs:
        return []
    shares = [o.share for o in outputs]
    if all(sh is None for sh in shares):
        qty_all = sum((Decimal(o.quantity) for o in outputs), ZERO)
        parts = [total * Decimal(o.quantity) / qty_all if qty_all else ZERO for o in outputs]
    else:
        parts = [total * Decimal(sh or 0) / HUNDRED for sh in shares]
    return [(p / Decimal(o.quantity)).quantize(Q4, rounding=ROUND_HALF_UP) if Decimal(o.quantity) else ZERO
            for p, o in zip(parts, outputs)]


def _validate(s: Session, entity_id: int, d: ProductionData) -> None:
    from finora.services import stock
    if not (d.name or "").strip():
        raise ValueError("Dê um nome ao lote (ex.: Azeite safra 2026 – lote 1).")
    if not d.inputs:
        raise ValueError("Inclua pelo menos um insumo usado.")
    if not d.outputs:
        raise ValueError("Inclua pelo menos um produto obtido.")
    for ln in d.inputs + d.outputs:
        it = s.get(Item, ln.item_id)
        if it is None or it.entity_id != entity_id:
            raise ValueError("Item inválido no lote.")
        if Decimal(ln.quantity) <= 0:
            raise ValueError(f"Quantidade de {it.name} precisa ser maior que zero.")
        stock.qty(ln.quantity)
    if {o.item_id for o in d.outputs} & {i.item_id for i in d.inputs}:
        raise ValueError("Um mesmo item não pode ser insumo e produto do mesmo lote.")
    if _money(d.extra_cost) < 0:
        raise ValueError("Outros custos não podem ser negativos.")
    shares = [o.share for o in d.outputs]
    if any(sh is not None for sh in shares):
        if any(sh is None or Decimal(sh) < 0 for sh in shares):
            raise ValueError("Informe o % do custo de todos os produtos (ou deixe todos em branco para dividir "
                             "pela quantidade).")
        if sum((Decimal(sh) for sh in shares), ZERO) != HUNDRED:
            raise ValueError("Os % do custo dos produtos precisam somar 100%.")


def _next_number(s: Session, entity_id: int) -> int:
    return (s.scalar(select(func.max(Production.number)).where(Production.entity_id == entity_id)) or 0) + 1


def save(s: Session, entity_id: int, d: ProductionData, production_id: int | None = None) -> int:
    """Grava o lote em andamento (novo ou alterado). Concluído: reabra antes de mudar."""
    _validate(s, entity_id, d)
    if production_id is None:
        p = Production(entity_id=entity_id, number=_next_number(s, entity_id), status="open")
        s.add(p)
    else:
        p = _get(s, production_id, entity_id)
        if p.status != "open":
            raise ValueError("Lote concluído não muda. Reabra o lote para alterar.")
        for old in s.scalars(select(ProductionLine).where(ProductionLine.production_id == p.id)):
            s.delete(old)
    p.name, p.day = d.name.strip()[:80], d.day
    p.location_id, p.extra_cost = d.location_id, _money(d.extra_cost)
    p.notes = (d.notes or "").strip()[:300] or None
    s.flush()
    for role, lines in (("in", d.inputs), ("out", d.outputs)):
        for ln in lines:
            s.add(ProductionLine(production_id=p.id, role=role, item_id=ln.item_id,
                                 quantity=Decimal(ln.quantity).quantize(Decimal("0.001")),
                                 share=Decimal(ln.share).quantize(Decimal("0.001")) if ln.share is not None else None))
    s.commit()
    return p.id


def _get(s: Session, production_id: int, entity_id: int | None = None) -> Production:
    p = s.get(Production, production_id)
    if p is None or (entity_id is not None and p.entity_id != entity_id):
        raise ValueError("Lote não encontrado.")
    return p


def _lines(s: Session, production_id: int) -> list[ProductionLine]:
    return list(s.scalars(select(ProductionLine).where(ProductionLine.production_id == production_id)
                          .order_by(ProductionLine.id)))


def estimate(s: Session, entity_id: int, d: ProductionData) -> tuple[Decimal, list[Decimal]]:
    """Prévia (sem gravar): custo total do lote e custo por unidade de cada produto, pelo custo médio do dia."""
    from finora.services import stock
    total = _money(d.extra_cost)
    for ln in d.inputs:
        total += Decimal(ln.quantity) * stock.average_cost(s, entity_id, ln.item_id, until=d.day)
    total = _money(total)
    return total, split_costs(total, d.outputs)


def finish(s: Session, production_id: int) -> Decimal:
    """Conclui: tira os insumos e põe os produtos no estoque. Devolve o custo total do lote."""
    from finora.services import stock
    p = _get(s, production_id)
    if p.status != "open":
        raise ValueError("Esse lote já está concluído.")
    eid = p.entity_id
    stock._check_day(s, eid, p.day)
    loc = stock._loc(s, eid, p.location_id)
    lines = _lines(s, p.id)
    inputs = [ln for ln in lines if ln.role == "in"]
    outputs = [ln for ln in lines if ln.role == "out"]
    need: dict[int, Decimal] = {}
    for ln in inputs:
        need[ln.item_id] = need.get(ln.item_id, ZERO) + Decimal(ln.quantity)
    for item_id, q in need.items():
        have = stock.balance(s, eid, item_id, loc)
        if q > have:
            it = s.get(Item, item_id)
            raise ValueError(f"Falta {it.name} no estoque: o lote usa {stock.fmt_qty(q, it.unit)} e há "
                             f"{stock.fmt_qty(have, it.unit)} no local. Lance a entrada antes de concluir.")
    total = _money(p.extra_cost)
    doc = f"Lote {p.number}"
    for ln in inputs:
        ln.unit_cost = stock.average_cost(s, eid, ln.item_id, until=p.day)
        total += Decimal(ln.quantity) * ln.unit_cost
        s.add(StockMove(entity_id=eid, item_id=ln.item_id, location_id=loc, day=p.day, kind="prod_out",
                        quantity=-Decimal(ln.quantity), production_id=p.id, document_no=doc, notes=p.name))
    total = _money(total)
    costs = split_costs(total, [Line(o.item_id, o.quantity, o.share) for o in outputs])
    for ln, cost in zip(outputs, costs):
        ln.unit_cost = cost
        s.add(StockMove(entity_id=eid, item_id=ln.item_id, location_id=loc, day=p.day, kind="prod_in",
                        quantity=Decimal(ln.quantity), unit_cost=cost, production_id=p.id, document_no=doc,
                        notes=p.name))
    p.status = "done"
    s.commit()
    return total


def reopen(s: Session, production_id: int) -> None:
    """Desfaz a conclusão: os insumos voltam e os produtos saem do estoque (se ainda estiverem lá)."""
    from finora.services import stock
    p = _get(s, production_id)
    if p.status != "done":
        return
    eid = p.entity_id
    stock._check_day(s, eid, p.day)
    moves = list(s.scalars(select(StockMove).where(StockMove.production_id == p.id)))
    for m in moves:
        if m.kind == "prod_in":
            have = stock.balance(s, eid, m.item_id, m.location_id)
            if Decimal(m.quantity) > have:
                it = s.get(Item, m.item_id)
                raise ValueError(f"Não dá para reabrir: parte de {it.name} desse lote já saiu do estoque (há "
                                 f"{stock.fmt_qty(have, it.unit)}). Desfaça as vendas ou saídas antes.")
    for m in moves:
        s.delete(m)
    for ln in _lines(s, p.id):
        ln.unit_cost = None
    p.status = "open"
    s.commit()


def delete(s: Session, production_id: int) -> None:
    p = _get(s, production_id)
    if p.status != "open":
        raise ValueError("Reabra o lote antes de excluir.")
    s.delete(p)
    s.commit()


# ---------- consultas ----------
def _yield_text(inp: list[tuple], out: list[tuple]) -> str:
    """Rendimento do produto principal sobre o insumo principal: '15 L por 100 kg' ou '92%' (mesma unidade)."""
    if not inp or not out:
        return ""
    (_n1, q_in, u_in), (_n2, q_out, u_out) = inp[0], out[0]
    if not q_in:
        return ""
    from finora.services import stock
    ratio = Decimal(q_out) / Decimal(q_in)
    if u_in == u_out:
        return f"{(ratio * HUNDRED).quantize(Decimal('0.1'))}%".replace(".", ",")
    return f"{stock.fmt_qty(ratio * HUNDRED, u_out)} por 100 {u_in}"


@dataclass(frozen=True)
class ProductionView:
    id: int
    number: int
    name: str
    day: date
    status: str
    inputs: str                           # "Azeitona 1.000 kg"
    outputs: str                          # "Azeite 150 L"
    total_cost: Decimal
    unit_cost: Decimal | None             # do produto principal
    yield_text: str

    @property
    def status_label(self) -> str:
        return STATUS.get(self.status, self.status)


@dataclass(frozen=True)
class LineView:
    item_id: int
    name: str
    unit: str
    quantity: Decimal
    share: Decimal | None
    unit_cost: Decimal | None

    @property
    def total(self) -> Decimal | None:
        return _money(self.quantity * self.unit_cost) if self.unit_cost is not None else None


@dataclass(frozen=True)
class ProductionDetail:
    id: int
    number: int
    name: str
    day: date
    status: str
    location_id: int | None
    extra_cost: Decimal
    notes: str
    inputs: list[LineView] = field(default_factory=list)
    outputs: list[LineView] = field(default_factory=list)

    @property
    def total_cost(self) -> Decimal | None:
        if self.status != "done":
            return None
        return _money(sum((ln.total or ZERO for ln in self.inputs), ZERO) + self.extra_cost)

    @property
    def yield_text(self) -> str:
        return _yield_text([(i.name, i.quantity, i.unit) for i in self.inputs],
                           [(o.name, o.quantity, o.unit) for o in self.outputs])


def get(s: Session, production_id: int) -> ProductionDetail:
    p = _get(s, production_id)
    views = {"in": [], "out": []}
    for ln, name, unit in s.execute(select(ProductionLine, Item.name, Item.unit)
                                    .join(Item, Item.id == ProductionLine.item_id)
                                    .where(ProductionLine.production_id == p.id).order_by(ProductionLine.id)):
        views[ln.role].append(LineView(ln.item_id, name, unit, Decimal(ln.quantity), ln.share, ln.unit_cost))
    return ProductionDetail(p.id, p.number, p.name, p.day, p.status, p.location_id, Decimal(p.extra_cost),
                            p.notes or "", views["in"], views["out"])


def list_productions(s: Session, entity_id: int, first: date | None = None, last: date | None = None,
                     status: str | None = None, search: str = "") -> list[ProductionView]:
    from finora.services import stock
    q = select(Production).where(Production.entity_id == entity_id)
    if first is not None:
        q = q.where(Production.day >= first)
    if last is not None:
        q = q.where(Production.day <= last)
    if status:
        q = q.where(Production.status == status)
    if search.strip():
        text = search.strip()
        cond = func.lower(Production.name).like(f"%{text.lower()}%")
        if text.isdigit():
            cond = cond | (Production.number == int(text))
        q = q.where(cond)
    out = []
    for p in s.scalars(q.order_by(Production.day.desc(), Production.number.desc())):
        d = get(s, p.id)

        def names(lines):
            return ", ".join(f"{ln.name} {stock.fmt_qty(ln.quantity, ln.unit)}" for ln in lines)
        main = d.outputs[0] if d.outputs else None
        out.append(ProductionView(p.id, p.number, p.name, p.day, p.status, names(d.inputs), names(d.outputs),
                                  d.total_cost or ZERO, main.unit_cost if main else None, d.yield_text))
    return out


@dataclass(frozen=True)
class ProducedRow:
    item_id: int
    name: str
    unit: str
    quantity: Decimal
    cost: Decimal
    batches: int

    @property
    def unit_cost(self) -> Decimal | None:
        return (self.cost / self.quantity).quantize(Q4, rounding=ROUND_HALF_UP) if self.quantity else None


def summary(s: Session, entity_id: int, first: date, last: date) -> list[ProducedRow]:
    """Por produto: quanto foi produzido no período (lotes concluídos), custo total e custo médio por unidade."""
    rows: dict[int, list] = {}
    q = (select(ProductionLine, Item.name, Item.unit)
         .join(Production, Production.id == ProductionLine.production_id)
         .join(Item, Item.id == ProductionLine.item_id)
         .where(Production.entity_id == entity_id, Production.status == "done", ProductionLine.role == "out",
                Production.day >= first, Production.day <= last))
    for ln, name, unit in s.execute(q):
        r = rows.setdefault(ln.item_id, [name, unit, ZERO, ZERO, set()])
        r[2] += Decimal(ln.quantity)
        r[3] += Decimal(ln.quantity) * Decimal(ln.unit_cost or 0)
        r[4].add(ln.production_id)
    return sorted((ProducedRow(k, v[0], v[1], v[2], _money(v[3]), len(v[4])) for k, v in rows.items()),
                  key=lambda r: r.name.lower())
