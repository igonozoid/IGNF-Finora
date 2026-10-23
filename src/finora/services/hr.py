"""RH (módulo "hr", decisão D4), como no IgnControl: o funcionário é um contato "Trabalha para mim" com um perfil de
RH (função, admissão, INSS patronal…) e um histórico de salários, férias, 13º e benefícios mensais.

Salário atual = o último reajuste (líquido, se informado; senão o nominal) ou o salário inicial do perfil. A folha
do mês soma salário atual + benefícios ativos. O custo estimado acrescenta INSS patronal (alíquota do perfil), FGTS
de 8% e as provisões de 13º (1/12) e de 1/3 de férias (1/36), com INSS e FGTS sobre elas.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.orm import Session

from finora.core import money
from finora.models import Contact, EmployeeProfile, EmployeeRecord
from finora.services import contacts, scope

STAFF = {"domestic_rural": "Doméstico / rural", "office": "Escritório"}
EMPLOYMENT = ("CLT", "Diarista", "Informal", "Estagiário", "Consultoria", "Autônomo")
KINDS = {"salary": "Salário", "vacation": "Férias", "thirteenth": "13º salário", "benefit": "Benefício"}
FGTS = Decimal("0.08")
THIRTEENTH = Decimal(1) / Decimal(12)
VACATION_THIRD = Decimal(1) / Decimal(36)
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
PROFILE_TEXT = {"job_title": 80, "employment_type": 30, "union_name": 120, "workplace": 120}


def _q(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class EmployeeView:
    contact_id: int
    name: str
    job_title: str
    staff_category: str
    employment_type: str
    admission_date: date | None
    termination_date: date | None
    salary: Decimal              # salário atual
    benefits: Decimal            # benefícios ativos por mês

    @property
    def active(self) -> bool:
        return self.termination_date is None or self.termination_date > date.today()

    @property
    def total(self) -> Decimal:
        return self.salary + self.benefits


@dataclass(frozen=True)
class Summary:
    count: int
    active: int
    salaries: Decimal
    benefits: Decimal

    @property
    def payroll(self) -> Decimal:
        return self.salaries + self.benefits


@dataclass(frozen=True)
class RecordView:
    id: int
    kind: str
    day: date | None
    end_day: date | None
    period: str
    name: str
    amount: Decimal | None
    net_amount: Decimal | None
    active: bool
    notes: str


def _salary(s: Session, contact_id: int, profile: EmployeeProfile | None) -> Decimal:
    last = s.scalars(select(EmployeeRecord).where(EmployeeRecord.contact_id == contact_id,
                                                  EmployeeRecord.kind == "salary")
                     .order_by(EmployeeRecord.day.desc(), EmployeeRecord.id.desc())).first()
    value = (last.net_amount or last.amount) if last is not None else None
    if value is None and profile is not None:
        value = profile.initial_salary
    return _q(value or 0)


def _benefits(s: Session, contact_id: int) -> Decimal:
    return _q(s.scalar(select(func.coalesce(func.sum(EmployeeRecord.amount), 0)).where(
        EmployeeRecord.contact_id == contact_id, EmployeeRecord.kind == "benefit", EmployeeRecord.active)))


def list_employees(s: Session, entity_id: int, search: str = "", staff: str | None = None,
                   status: str | None = "active") -> tuple[list[EmployeeView], Summary]:
    """Contatos "Trabalha para mim" com o perfil de RH. `status`: active, terminated ou None (todos). O resumo soma
    os da lista."""
    q = (select(Contact, EmployeeProfile).outerjoin(EmployeeProfile, EmployeeProfile.contact_id == Contact.id)
         .where(scope.contacts(entity_id), Contact.is_employee).order_by(func.lower(Contact.name)))
    if search.strip():
        q = q.where(func.lower(Contact.name).like(f"%{search.strip().lower()}%"))
    out = []
    for c, p in s.execute(q):
        if staff and (p.staff_category if p else "domestic_rural") != staff:
            continue
        v = EmployeeView(c.id, c.name, (p.job_title if p else None) or "",
                         p.staff_category if p else "domestic_rural", (p.employment_type if p else None) or "",
                         p.admission_date if p else None, p.termination_date if p else None,
                         _salary(s, c.id, p), _benefits(s, c.id))
        if status == "active" and not v.active or status == "terminated" and v.active:
            continue
        out.append(v)
    summary = Summary(len(out), sum(1 for v in out if v.active), sum((v.salary for v in out), ZERO),
                      sum((v.benefits for v in out), ZERO))
    return out, summary


def add_employee(s: Session, entity_id: int, name: str) -> int:
    """Funcionário novo ou um contato que já existe: ganha o papel "Trabalha para mim" e o perfil de RH."""
    if not (name or "").strip():
        raise ValueError("Digite o nome do funcionário.")
    cid = contacts.get_or_create(s, entity_id, name)
    c = s.get(Contact, cid)
    c.is_employee = True
    if s.scalar(select(EmployeeProfile.id).where(EmployeeProfile.contact_id == cid)) is None:
        s.add(EmployeeProfile(entity_id=entity_id, contact_id=cid, staff_category="domestic_rural"))
    s.commit()
    return cid


def get_profile(s: Session, contact_id: int) -> dict:
    p = s.scalar(select(EmployeeProfile).where(EmployeeProfile.contact_id == contact_id))
    keys = ("job_title", "staff_category", "employment_type", "union_name", "workplace", "inss_rate",
            "monthly_hours", "initial_salary", "admission_date", "termination_date", "notes")
    if p is None:
        return {k: ("domestic_rural" if k == "staff_category" else None) for k in keys}
    return {k: getattr(p, k) for k in keys}


def save_profile(s: Session, entity_id: int, contact_id: int, **data) -> None:
    """Grava o perfil. `inss_rate` em fração (0.08 = 8%). Datas como `date`."""
    c = s.get(Contact, contact_id)
    if c is None:
        raise ValueError("Funcionário não encontrado.")
    p = s.scalar(select(EmployeeProfile).where(EmployeeProfile.contact_id == contact_id))
    if p is None:
        p = EmployeeProfile(entity_id=entity_id, contact_id=contact_id)
        s.add(p)
    for key, size in PROFILE_TEXT.items():
        if key in data:
            v = (data[key] or "").strip() or None
            if v and len(v) > size:
                raise ValueError("Texto longo demais em um dos campos.")
            setattr(p, key, v)
    if "staff_category" in data:
        if data["staff_category"] not in STAFF:
            raise ValueError("Escolha doméstico/rural ou escritório.")
        p.staff_category = data["staff_category"]
    for key in ("inss_rate", "monthly_hours", "initial_salary"):
        if key in data:
            v = data[key]
            if v is not None and Decimal(v) < 0:
                raise ValueError("Valores não podem ser negativos.")
            if key == "inss_rate" and v is not None and Decimal(v) > 1:
                raise ValueError("Alíquota do INSS em fração: 8% = 0,08.")
            setattr(p, key, v)
    for key in ("admission_date", "termination_date", "notes"):
        if key in data:
            setattr(p, key, (data[key] or "").strip() or None if key == "notes" else data[key])
    if p.admission_date and p.termination_date and p.termination_date < p.admission_date:
        raise ValueError("A data de saída é antes da admissão.")
    c.is_employee = True
    s.commit()


def records(s: Session, contact_id: int, kind: str | None = None) -> list[RecordView]:
    q = select(EmployeeRecord).where(EmployeeRecord.contact_id == contact_id)
    if kind:
        q = q.where(EmployeeRecord.kind == kind)
    q = q.order_by(EmployeeRecord.kind, EmployeeRecord.day.desc(), EmployeeRecord.id.desc())
    return [RecordView(r.id, r.kind, r.day, r.end_day, r.period or "", r.name or "", r.amount, r.net_amount,
                       bool(r.active), r.notes or "") for r in s.scalars(q)]


def save_record(s: Session, entity_id: int, contact_id: int, record_id: int | None = None, *, kind: str,
                day: date | None = None, end_day: date | None = None, period: str = "", name: str = "",
                amount: Decimal | None = None, net_amount: Decimal | None = None, active: bool = True,
                notes: str = "") -> int:
    if kind not in KINDS:
        raise ValueError("Tipo de registro inválido.")
    if kind == "salary" and (day is None or not (amount or net_amount)):
        raise ValueError("Reajuste de salário precisa da data e do valor.")
    if kind == "vacation" and not (period.strip() or day):
        raise ValueError("Férias: informe o período aquisitivo ou o início do gozo.")
    if kind == "vacation" and day and end_day and end_day < day:
        raise ValueError("O fim das férias é antes do início.")
    if kind == "thirteenth" and not period.strip():
        raise ValueError("13º: informe o ano.")
    if kind == "benefit" and (not name.strip() or amount is None):
        raise ValueError("Benefício precisa do nome e do valor por mês.")
    for v in (amount, net_amount):
        if v is not None and Decimal(v) < 0:
            raise ValueError("Valores não podem ser negativos.")
    r = s.get(EmployeeRecord, record_id) if record_id else None
    if r is None:
        r = EmployeeRecord(entity_id=entity_id, contact_id=contact_id, kind=kind)
        s.add(r)
    r.kind, r.day, r.end_day = kind, day, end_day if kind == "vacation" else None
    r.period, r.name = period.strip()[:30] or None, name.strip()[:80] or None
    r.amount, r.net_amount = amount, net_amount if kind == "salary" else None
    r.active, r.notes = bool(active) if kind == "benefit" else True, notes.strip()[:300] or None
    s.commit()
    return r.id


def delete_record(s: Session, record_id: int) -> None:
    r = s.get(EmployeeRecord, record_id)
    if r is not None:
        s.delete(r)
        s.commit()


@dataclass(frozen=True)
class Cost:
    salary: Decimal
    inss_rate: Decimal
    lines: list[tuple[str, Decimal]] = field(default_factory=list)     # encargos e provisões

    @property
    def charges(self) -> Decimal:
        return sum((v for _l, v in self.lines), ZERO)

    @property
    def total(self) -> Decimal:
        return self.salary + self.charges


def cost(s: Session, contact_id: int) -> Cost:
    """Custo mensal estimado do funcionário (mesma conta do IgnControl)."""
    p = s.scalar(select(EmployeeProfile).where(EmployeeProfile.contact_id == contact_id))
    base = _salary(s, contact_id, p)
    rate = Decimal(p.inss_rate) if p is not None and p.inss_rate is not None else Decimal(0)
    thirteenth, third = base * THIRTEENTH, base * VACATION_THIRD
    pct = f"{rate * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    lines = [(f"INSS patronal ({pct}%)", base * rate), ("FGTS (8%)", base * FGTS),
             ("Provisão de 13º (1/12)", thirteenth), ("INSS sobre o 13º", thirteenth * rate),
             ("FGTS sobre o 13º", thirteenth * FGTS), ("Provisão de 1/3 de férias", third),
             ("INSS sobre 1/3 de férias", third * rate), ("FGTS sobre 1/3 de férias", third * FGTS)]
    return Cost(base, rate, [(label, _q(v)) for label, v in lines])


def merge_into(s: Session, keep_id: int, drop_id: int) -> None:
    """Mesclar contatos: o histórico de RH vai para o mantido; o perfil, se o mantido não tiver um."""
    from sqlalchemy import update
    s.execute(update(EmployeeRecord).where(EmployeeRecord.contact_id == drop_id).values(contact_id=keep_id)
              .execution_options(synchronize_session=False))
    if s.scalar(select(EmployeeProfile.id).where(EmployeeProfile.contact_id == keep_id)) is None:
        s.execute(update(EmployeeProfile).where(EmployeeProfile.contact_id == drop_id).values(contact_id=keep_id)
                  .execution_options(synchronize_session=False))
    else:
        s.execute(sql_delete(EmployeeProfile).where(EmployeeProfile.contact_id == drop_id))


def fmt_rate(rate: Decimal | None) -> str:
    """0.08 -> "8"; para o campo da tela (em %)."""
    if rate is None:
        return ""
    return money.fmt(Decimal(rate) * 100).split(" ", 1)[-1].rstrip("0").rstrip(",")
