"""Agricultura (módulo "rural"): propriedades, áreas e o que acontece em cada área.

- Propriedade (fazenda, sítio) tem áreas: talhão, pomar, pasto/piquete, apiário… com cultura e hectares.
- Atividade numa área (plantio, adubação, poda, colheita…): os insumos usados saem do estoque na hora, pelo custo
  médio do dia ("Usado na lavoura"); outros custos (mão de obra, máquina) entram só no custo da área.
- Ocorrência (geada, praga, quebra de cerca) é uma atividade sem custo obrigatório, para o histórico.
- Colheita: o produto entra no estoque ("Colheita"). O custo dele é o que a área acumulou e ainda não foi para
  uma colheita (insumos + outros custos de todas as atividades até a data). Dá para informar outro valor (ex.:
  levar só metade, se ainda vem outra colheita da mesma safra).
- Custo por área: o que cada área gastou no período, por hectare, e quanto colheu.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core.money import CENT
from finora.models import Farm, FarmActivity, FarmArea, Item, StockMove

AREA_KINDS = {"field": "Lavoura / talhão", "orchard": "Pomar", "pasture": "Pasto / piquete", "apiary": "Apiário",
              "other": "Outra"}
ACTIVITIES = {"planting": "Plantio", "fertilizing": "Adubação", "spraying": "Pulverização / defensivo",
              "pruning": "Poda", "irrigation": "Irrigação", "cultivation": "Trato / roçada", "harvest": "Colheita",
              "maintenance": "Manutenção", "occurrence": "Ocorrência (geada, praga…)", "other": "Outra"}
ZERO = Decimal("0")
Q4 = Decimal("0.0001")


def _money(v) -> Decimal:
    return Decimal(v or 0).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------- propriedades e áreas ----------
@dataclass(frozen=True)
class FarmView:
    id: int
    name: str
    city: str
    notes: str
    is_active: bool


def farms(s: Session, entity_id: int, include_inactive: bool = False) -> list[FarmView]:
    q = select(Farm).where(Farm.entity_id == entity_id)
    if not include_inactive:
        q = q.where(Farm.is_active)
    return [FarmView(f.id, f.name, f.city or "", f.notes or "", f.is_active)
            for f in s.scalars(q.order_by(func.lower(Farm.name)))]


def save_farm(s: Session, entity_id: int, *, name: str, city: str = "", notes: str = "", is_active: bool = True,
              farm_id: int | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Dê um nome à propriedade.")
    dup = s.scalar(select(Farm.id).where(Farm.entity_id == entity_id, func.lower(Farm.name) == name.lower(),
                                         Farm.id != (farm_id or 0)))
    if dup:
        raise ValueError("Já existe uma propriedade com esse nome.")
    if farm_id is None:
        f = Farm(entity_id=entity_id)
        s.add(f)
    else:
        f = s.get(Farm, farm_id)
        if f is None or f.entity_id != entity_id:
            raise ValueError("Propriedade não encontrada.")
    f.name, f.city, f.notes, f.is_active = name[:80], (city or "").strip()[:80] or None, \
        (notes or "").strip()[:300] or None, is_active
    s.commit()
    return f.id


@dataclass(frozen=True)
class AreaView:
    id: int
    farm_id: int
    farm: str
    name: str
    kind: str
    crop: str
    hectares: Decimal | None
    units: int | None
    notes: str
    is_active: bool
    pending_cost: Decimal = ZERO          # custo acumulado que ainda não foi para uma colheita

    @property
    def kind_label(self) -> str:
        return AREA_KINDS.get(self.kind, self.kind)

    @property
    def label(self) -> str:
        return f"{self.farm} › {self.name}"


def areas(s: Session, entity_id: int, farm_id: int | None = None, include_inactive: bool = False,
          kind: str | None = None) -> list[AreaView]:
    q = (select(FarmArea, Farm.name).join(Farm, Farm.id == FarmArea.farm_id)
         .where(FarmArea.entity_id == entity_id))
    if farm_id is not None:
        q = q.where(FarmArea.farm_id == farm_id)
    if kind:
        q = q.where(FarmArea.kind == kind)
    if not include_inactive:
        q = q.where(FarmArea.is_active, Farm.is_active)
    rows = list(s.execute(q.order_by(func.lower(Farm.name), func.lower(FarmArea.name))))
    pend = _pending_all(s, entity_id)
    return [AreaView(a.id, a.farm_id, farm, a.name, a.kind, a.crop or "", a.hectares, a.units, a.notes or "",
                     a.is_active, pend.get(a.id, ZERO)) for a, farm in rows]


def save_area(s: Session, entity_id: int, *, farm_id: int, name: str, kind: str = "field", crop: str = "",
              hectares=None, units=None, notes: str = "", is_active: bool = True, area_id: int | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Dê um nome à área (ex.: Talhão 1, Pomar de cima, Piquete 3).")
    f = s.get(Farm, farm_id)
    if f is None or f.entity_id != entity_id:
        raise ValueError("Escolha a propriedade.")
    if kind not in AREA_KINDS:
        raise ValueError("Tipo de área inválido.")
    dup = s.scalar(select(FarmArea.id).where(FarmArea.farm_id == farm_id,
                                             func.lower(FarmArea.name) == name.lower(),
                                             FarmArea.id != (area_id or 0)))
    if dup:
        raise ValueError("Essa propriedade já tem uma área com esse nome.")
    try:
        ha = Decimal(str(hectares).replace(",", ".")).quantize(Q4) if hectares not in (None, "") else None
        n = int(units) if units not in (None, "") else None
    except Exception:
        raise ValueError("Tamanho ou quantidade inválidos.")
    if (ha is not None and ha < 0) or (n is not None and n < 0):
        raise ValueError("Tamanho e quantidade não podem ser negativos.")
    if area_id is None:
        a = FarmArea(entity_id=entity_id)
        s.add(a)
    else:
        a = s.get(FarmArea, area_id)
        if a is None or a.entity_id != entity_id:
            raise ValueError("Área não encontrada.")
    a.farm_id, a.name, a.kind = farm_id, name[:80], kind
    a.crop, a.hectares, a.units = (crop or "").strip()[:80] or None, ha, n
    a.notes, a.is_active = (notes or "").strip()[:300] or None, is_active
    s.commit()
    return a.id


# ---------- atividades ----------
@dataclass
class Use:
    item_id: int
    quantity: Decimal


@dataclass
class ActivityData:
    area_id: int
    day: date
    kind: str
    description: str = ""
    inputs: list[Use] = field(default_factory=list)       # insumos usados (saem do estoque)
    harvest: list[Use] = field(default_factory=list)      # só na colheita: produtos que entram no estoque
    other_cost: Decimal = ZERO
    harvest_cost: Decimal | None = None                   # None = o custo acumulado da área
    location_id: int | None = None
    notes: str = ""


def _pending_all(s: Session, entity_id: int, until: date | None = None,
                 exclude_id: int | None = None) -> dict[int, Decimal]:
    """Área -> custo acumulado (insumos + outros) menos o que já foi para colheitas."""
    q = select(FarmActivity.area_id, func.sum(FarmActivity.inputs_cost + FarmActivity.other_cost
                                              - FarmActivity.harvest_cost)).where(FarmActivity.entity_id == entity_id)
    if until is not None:
        q = q.where(FarmActivity.day <= until)
    if exclude_id is not None:
        q = q.where(FarmActivity.id != exclude_id)
    return {a: _money(v) for a, v in s.execute(q.group_by(FarmActivity.area_id))}


def pending_cost(s: Session, entity_id: int, area_id: int, until: date | None = None,
                 exclude_id: int | None = None) -> Decimal:
    return max(_pending_all(s, entity_id, until, exclude_id).get(area_id, ZERO), ZERO)


def _validate(s: Session, entity_id: int, d: ActivityData) -> FarmArea:
    from finora.services import stock
    a = s.get(FarmArea, d.area_id)
    if a is None or a.entity_id != entity_id:
        raise ValueError("Escolha a área.")
    if d.kind not in ACTIVITIES:
        raise ValueError("Tipo de atividade inválido.")
    for u in d.inputs + d.harvest:
        it = s.get(Item, u.item_id)
        if it is None or it.entity_id != entity_id:
            raise ValueError("Item inválido.")
        if Decimal(u.quantity) <= 0:
            raise ValueError(f"Quantidade de {it.name} precisa ser maior que zero.")
        stock.qty(u.quantity)
    if d.kind == "harvest" and not d.harvest:
        raise ValueError("Informe o que foi colhido (o produto entra no estoque).")
    if d.kind != "harvest" and d.harvest:
        raise ValueError("Só a colheita põe produtos no estoque.")
    if _money(d.other_cost) < 0 or (d.harvest_cost is not None and _money(d.harvest_cost) < 0):
        raise ValueError("Custos não podem ser negativos.")
    return a


def suggested_harvest_cost(s: Session, entity_id: int, d: ActivityData, activity_id: int | None = None) -> Decimal:
    """Custo que a colheita leva: o acumulado da área até a data + os custos desta própria atividade."""
    from finora.services import stock
    own = _money(d.other_cost) + _money(sum((Decimal(u.quantity) * stock.average_cost(s, entity_id, u.item_id,
                                                                                         until=d.day)
                                             for u in d.inputs), ZERO))
    return pending_cost(s, entity_id, d.area_id, until=d.day, exclude_id=activity_id) + own


def _undo_moves(s: Session, act: FarmActivity) -> None:
    from finora.services import stock
    moves = list(s.scalars(select(StockMove).where(StockMove.activity_id == act.id)))
    for m in moves:
        if m.kind == "harvest":
            have = stock.balance(s, act.entity_id, m.item_id, m.location_id)
            if Decimal(m.quantity) > have:
                it = s.get(Item, m.item_id)
                raise ValueError(f"Parte de {it.name} dessa colheita já saiu do estoque (há "
                                 f"{stock.fmt_qty(have, it.unit)}). Desfaça as vendas ou saídas antes.")
    for m in moves:
        s.delete(m)
    s.flush()


def save_activity(s: Session, entity_id: int, d: ActivityData, activity_id: int | None = None) -> int:
    """Grava a atividade e mexe no estoque na hora (alterar refaz os movimentos)."""
    from finora.services import production, stock
    _validate(s, entity_id, d)
    stock._check_day(s, entity_id, d.day)
    if activity_id is None:
        act = FarmActivity(entity_id=entity_id)      # entra na sessão depois das contas (consultas dão flush)
    else:
        act = s.get(FarmActivity, activity_id)
        if act is None or act.entity_id != entity_id:
            raise ValueError("Atividade não encontrada.")
        stock._check_day(s, entity_id, act.day)
        _undo_moves(s, act)
    loc = stock._loc(s, entity_id, d.location_id)
    need: dict[int, Decimal] = {}
    for u in d.inputs:
        need[u.item_id] = need.get(u.item_id, ZERO) + Decimal(u.quantity)
    for item_id, q in need.items():
        have = stock.balance(s, entity_id, item_id, loc)
        if q > have:
            it = s.get(Item, item_id)
            s.rollback()
            raise ValueError(f"Falta {it.name} no estoque: a atividade usa {stock.fmt_qty(q, it.unit)} e há "
                             f"{stock.fmt_qty(have, it.unit)} no local. Lance a entrada antes.")
    if d.kind == "harvest":
        cost = _money(d.harvest_cost) if d.harvest_cost is not None else \
            suggested_harvest_cost(s, entity_id, d, activity_id)
    act.area_id, act.day, act.kind = d.area_id, d.day, d.kind
    act.description = (d.description or "").strip()[:200] or None
    act.other_cost, act.location_id = _money(d.other_cost), d.location_id
    act.notes = (d.notes or "").strip()[:300] or None
    act.inputs_cost = act.harvest_cost = ZERO
    s.add(act)
    s.flush()
    area = s.get(FarmArea, d.area_id)
    note = f"{area.name}: {ACTIVITIES[d.kind]}"
    used = ZERO
    for u in d.inputs:
        avg = stock.average_cost(s, entity_id, u.item_id, until=d.day)
        used += Decimal(u.quantity) * avg
        s.add(StockMove(entity_id=entity_id, item_id=u.item_id, location_id=loc, day=d.day, kind="farm_out",
                        quantity=-stock.qty(u.quantity), unit_cost=avg.quantize(Q4), activity_id=act.id,
                        notes=note[:300]))
    act.inputs_cost = _money(used)
    act.harvest_cost = ZERO
    if d.kind == "harvest":
        act.harvest_cost = cost
        lines = [production.Line(u.item_id, Decimal(u.quantity)) for u in d.harvest]
        for u, unit_cost in zip(d.harvest, production.split_costs(cost, lines)):
            s.add(StockMove(entity_id=entity_id, item_id=u.item_id, location_id=loc, day=d.day, kind="harvest",
                            quantity=stock.qty(u.quantity), unit_cost=unit_cost, activity_id=act.id,
                            notes=note[:300]))
    s.commit()
    return act.id


def delete_activity(s: Session, activity_id: int) -> None:
    """Exclui a atividade: os insumos voltam ao estoque e a colheita sai (se ainda estiver lá)."""
    from finora.services import stock
    act = s.get(FarmActivity, activity_id)
    if act is None:
        return
    stock._check_day(s, act.entity_id, act.day)
    _undo_moves(s, act)
    s.delete(act)
    s.commit()


# ---------- consultas ----------
@dataclass(frozen=True)
class UseView:
    item_id: int
    name: str
    unit: str
    quantity: Decimal
    unit_cost: Decimal | None


@dataclass(frozen=True)
class ActivityView:
    id: int
    day: date
    area_id: int
    area: str                             # "Fazenda › Talhão 1"
    kind: str
    description: str
    inputs: list[UseView]
    harvest: list[UseView]
    inputs_cost: Decimal
    other_cost: Decimal
    harvest_cost: Decimal
    location_id: int | None
    notes: str

    @property
    def kind_label(self) -> str:
        return ACTIVITIES.get(self.kind, self.kind)

    @property
    def total_cost(self) -> Decimal:
        return self.inputs_cost + self.other_cost

    def text(self, which: str) -> str:
        from finora.services import stock
        return ", ".join(f"{u.name} {stock.fmt_qty(u.quantity, u.unit)}" for u in getattr(self, which))


def _views(s: Session, acts: list[tuple]) -> list[ActivityView]:
    ids = [a.id for a, _f, _n in acts]
    uses: dict[int, dict[str, list]] = {i: {"in": [], "out": []} for i in ids}
    if ids:
        q = (select(StockMove, Item.name, Item.unit).join(Item, Item.id == StockMove.item_id)
             .where(StockMove.activity_id.in_(ids)).order_by(StockMove.id))
        for m, name, unit in s.execute(q):
            uses[m.activity_id]["out" if m.kind == "harvest" else "in"].append(
                UseView(m.item_id, name, unit, abs(Decimal(m.quantity)), m.unit_cost))
    return [ActivityView(a.id, a.day, a.area_id, f"{farm} › {area}", a.kind, a.description or "",
                         uses[a.id]["in"], uses[a.id]["out"], Decimal(a.inputs_cost), Decimal(a.other_cost),
                         Decimal(a.harvest_cost), a.location_id, a.notes or "") for a, farm, area in acts]


def _base_query(entity_id: int):
    return (select(FarmActivity, Farm.name, FarmArea.name)
            .join(FarmArea, FarmArea.id == FarmActivity.area_id).join(Farm, Farm.id == FarmArea.farm_id)
            .where(FarmActivity.entity_id == entity_id))


def list_activities(s: Session, entity_id: int, first: date | None = None, last: date | None = None,
                    farm_id: int | None = None, area_id: int | None = None, kind: str | None = None,
                    search: str = "") -> list[ActivityView]:
    q = _base_query(entity_id)
    if first is not None:
        q = q.where(FarmActivity.day >= first)
    if last is not None:
        q = q.where(FarmActivity.day <= last)
    if farm_id is not None:
        q = q.where(FarmArea.farm_id == farm_id)
    if area_id is not None:
        q = q.where(FarmActivity.area_id == area_id)
    if kind:
        q = q.where(FarmActivity.kind == kind)
    if search.strip():
        like = f"%{search.strip().lower()}%"
        q = q.where(func.lower(func.coalesce(FarmActivity.description, "")).like(like)
                    | func.lower(FarmArea.name).like(like))
    return _views(s, list(s.execute(q.order_by(FarmActivity.day.desc(), FarmActivity.id.desc()))))


def get_activity(s: Session, activity_id: int) -> ActivityView:
    act = s.get(FarmActivity, activity_id)
    if act is None:
        raise ValueError("Atividade não encontrada.")
    return _views(s, list(s.execute(_base_query(act.entity_id).where(FarmActivity.id == activity_id))))[0]


@dataclass(frozen=True)
class AreaCostRow:
    area_id: int
    area: str
    crop: str
    hectares: Decimal | None
    inputs_cost: Decimal
    other_cost: Decimal
    harvested: str                        # "Azeitona 3.000 kg"
    harvest_cost: Decimal
    activities: int

    @property
    def total(self) -> Decimal:
        return self.inputs_cost + self.other_cost

    @property
    def per_ha(self) -> Decimal | None:
        return _money(self.total / self.hectares) if self.hectares else None


def area_costs(s: Session, entity_id: int, first: date, last: date, farm_id: int | None = None) -> list[AreaCostRow]:
    """Por área: o que gastou no período (insumos + outros), por hectare, e o que colheu."""
    from finora.services import stock
    acts = list_activities(s, entity_id, first, last, farm_id=farm_id)
    info = {a.id: a for a in areas(s, entity_id, farm_id, include_inactive=True)}
    rows: dict[int, dict] = {}
    for a in acts:
        r = rows.setdefault(a.area_id, {"in": ZERO, "other": ZERO, "hc": ZERO, "n": 0, "got": {}})
        r["in"] += a.inputs_cost
        r["other"] += a.other_cost
        r["hc"] += a.harvest_cost
        r["n"] += 1
        for u in a.harvest:
            name, unit, q = r["got"].get(u.item_id, (u.name, u.unit, ZERO))
            r["got"][u.item_id] = (name, unit, q + u.quantity)
    out = []
    for area_id, r in rows.items():
        av = info.get(area_id)
        got = ", ".join(f"{n} {stock.fmt_qty(q, u)}" for n, u, q in r["got"].values())
        out.append(AreaCostRow(area_id, av.label if av else "?", av.crop if av else "", av.hectares if av else None,
                               _money(r["in"]), _money(r["other"]), got, _money(r["hc"]), r["n"]))
    return sorted(out, key=lambda r: r.area.lower())
