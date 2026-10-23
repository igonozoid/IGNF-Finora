"""Agenda (módulo "agenda", decisão D4): tarefas com data, recorrência e vínculo com contato ou lançamento, mais os
aniversários e datas importantes dos contatos. Vem do IgnControl.

Recorrente: concluir cria a próxima ocorrência (não há uma lista de futuras já criadas). Mensal em diante pode
fixar o dia do mês (dia 31 vira o último dia em mês mais curto).
"""
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from finora.core.current import current
from finora.models import Contact, Entry, Task
from finora.services import contacts, scope

RECURRENCES = {"none": "Não repete", "daily": "Todo dia", "weekly": "Toda semana", "fortnightly": "A cada 15 dias",
               "monthly": "Todo mês", "bimonthly": "A cada 2 meses", "quarterly": "A cada 3 meses",
               "semiannual": "A cada 6 meses", "yearly": "Todo ano"}
_DAYS = {"daily": 1, "weekly": 7, "fortnightly": 14}
_MONTHS = {"monthly": 1, "bimonthly": 2, "quarterly": 3, "semiannual": 6, "yearly": 12}
STATUS = {"open": "A fazer", "late": "Atrasadas", "done": "Feitas", "all": "Todas"}


@dataclass(frozen=True)
class TaskView:
    id: int
    title: str
    notes: str
    due_date: date | None
    status: str
    recurrence: str
    recurrence_day: int | None
    contact: str                 # nome do contato ("" = nenhum)
    entry_id: int | None
    entry_label: str             # "Luz — 10/11/2026" do lançamento ligado

    def late(self, today: date | None = None) -> bool:
        return self.status == "pending" and self.due_date is not None and self.due_date < (today or date.today())

    @property
    def recurrence_label(self) -> str:
        label = RECURRENCES.get(self.recurrence, "")
        if self.recurrence in _MONTHS and self.recurrence_day:
            label += f", dia {self.recurrence_day}"
        return label if self.recurrence != "none" else ""


def next_due(due: date, recurrence: str, day: int | None = None) -> date | None:
    """Próxima data de uma tarefa recorrente."""
    if recurrence in _DAYS:
        return due + timedelta(days=_DAYS[recurrence])
    if recurrence not in _MONTHS:
        return None
    m = due.month - 1 + _MONTHS[recurrence]
    year, month = due.year + m // 12, m % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day or due.day, last))


def _view(t: Task, contact: str | None, entry: Entry | None) -> TaskView:
    label = f"{entry.description or 'Lançamento'} — {entry.due_date:%d/%m/%Y}" if entry is not None else ""
    return TaskView(t.id, t.title, t.notes or "", t.due_date, t.status, t.recurrence, t.recurrence_day,
                    contact or "", t.entry_id, label)


def list_tasks(s: Session, entity_id: int, status: str = "open", search: str = "", first: date | None = None,
               last: date | None = None, today: date | None = None) -> list[TaskView]:
    """`status`: open (a fazer), late (atrasadas), done (feitas) ou all. Sem data vai para o fim."""
    today = today or date.today()
    q = (select(Task, Contact.name, Entry).outerjoin(Contact, Task.contact_id == Contact.id)
         .outerjoin(Entry, Task.entry_id == Entry.id).where(Task.entity_id == entity_id))
    if status == "open":
        q = q.where(Task.status == "pending")
    elif status == "late":
        q = q.where(Task.status == "pending", Task.due_date < today)
    elif status == "done":
        q = q.where(Task.status == "done")
    if search.strip():
        like = f"%{search.strip().lower()}%"
        q = q.where(or_(func.lower(Task.title).like(like), func.lower(Task.notes).like(like),
                        func.lower(Contact.name).like(like)))
    if first is not None:
        q = q.where(Task.due_date >= first)
    if last is not None:
        q = q.where(Task.due_date <= last)
    q = q.order_by(Task.due_date.is_(None), Task.due_date, Task.id)
    return [_view(t, name, e) for t, name, e in s.execute(q)]


def counts(s: Session, entity_id: int, today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    base = select(func.count(Task.id)).where(Task.entity_id == entity_id)
    return {"open": s.scalar(base.where(Task.status == "pending")),
            "late": s.scalar(base.where(Task.status == "pending", Task.due_date < today)),
            "done": s.scalar(base.where(Task.status == "done")),
            "all": s.scalar(base)}


def entry_choices(s: Session, entity_id: int, keep_id: int | None = None) -> list[tuple[int, str]]:
    """Lançamentos em aberto para ligar a uma tarefa (ex.: "confirmar o pagamento da luz"), e o já ligado."""
    q = (select(Entry).where(Entry.entity_id == entity_id, or_(Entry.status == "pending", Entry.id == keep_id))
         .order_by(Entry.due_date, Entry.id).limit(300))
    return [(e.id, f"{e.due_date:%d/%m/%Y} · {e.description or 'Sem descrição'}") for e in s.scalars(q)]


def save(s: Session, entity_id: int, task_id: int | None = None, *, title: str, due_date: date | None = None,
         notes: str = "", recurrence: str = "none", recurrence_day: int | None = None, contact: str | None = None,
         entry_id: int | None = None) -> int:
    title = (title or "").strip()
    if not title:
        raise ValueError("Escreva o que precisa ser feito.")
    if len(title) > 200:
        raise ValueError("Título longo demais (até 200 letras).")
    if recurrence not in RECURRENCES:
        raise ValueError("Recorrência inválida.")
    if recurrence != "none" and due_date is None:
        raise ValueError("Tarefa que se repete precisa de data.")
    if recurrence not in _MONTHS:
        recurrence_day = None
    elif recurrence_day is not None and not 1 <= recurrence_day <= 31:
        raise ValueError("Dia do mês vai de 1 a 31.")
    if entry_id is not None:
        e = s.get(Entry, entry_id)
        if e is None or e.entity_id != entity_id:
            raise ValueError("Lançamento não encontrado.")
    t = s.get(Task, task_id) if task_id else None
    if t is None:
        t = Task(entity_id=entity_id, status="pending", created_by=(current.user_name or "")[:80] or None)
        s.add(t)
    t.title, t.due_date, t.notes = title, due_date, (notes or "").strip() or None
    t.recurrence, t.recurrence_day = recurrence, recurrence_day
    t.contact_id = contacts.get_or_create(s, entity_id, contact)
    t.entry_id = entry_id
    s.commit()
    return t.id


def complete(s: Session, task_id: int, now: datetime | None = None) -> int | None:
    """Marca como feita. Recorrente: cria a próxima (se ainda não houver uma em aberto) e devolve o id dela."""
    t = s.get(Task, task_id)
    if t is None or t.status == "done":
        return None
    t.status, t.done_at = "done", (now or datetime.now()).replace(microsecond=0)
    new_id = None
    nxt = next_due(t.due_date, t.recurrence, t.recurrence_day) if t.due_date else None
    if nxt is not None:
        open_later = s.scalar(select(Task.id).where(Task.entity_id == t.entity_id, Task.status == "pending",
                                                    Task.title == t.title, Task.recurrence == t.recurrence,
                                                    Task.due_date > t.due_date))
        if open_later is None:
            n = Task(entity_id=t.entity_id, title=t.title, notes=t.notes, due_date=nxt, status="pending",
                     recurrence=t.recurrence, recurrence_day=t.recurrence_day, contact_id=t.contact_id,
                     created_by=t.created_by)
            s.add(n)
            s.flush()
            new_id = n.id
    s.commit()
    return new_id


def reopen(s: Session, task_id: int) -> None:
    t = s.get(Task, task_id)
    if t is not None:
        t.status, t.done_at = "pending", None
        s.commit()


def delete(s: Session, task_id: int) -> None:
    t = s.get(Task, task_id)
    if t is not None:
        s.delete(t)
        s.commit()


@dataclass(frozen=True)
class DayItem:
    day: date
    kind: str            # task | done | birthday | important
    text: str
    task_id: int | None = None


def occurrences(s: Session, entity_id: int, first: date, last: date) -> list[DayItem]:
    """Tudo o que cai entre `first` e `last` para o calendário: tarefas (abertas e feitas), aniversários e datas
    importantes dos contatos (que voltam todo ano)."""
    out = [DayItem(t.due_date, "done" if t.status == "done" else "task", t.title, t.id)
           for t in list_tasks(s, entity_id, "all", first=first, last=last)]
    q = select(Contact.name, Contact.birthday, Contact.important_date, Contact.important_label).where(
        scope.contacts(entity_id), Contact.birthday.is_not(None) | Contact.important_date.is_not(None))
    for name, birthday, important, label in s.execute(q):
        for d, kind, text in ((birthday, "birthday", f"Aniversário de {name}"),
                              (important, "important", f"{label or 'Data importante'} — {name}")):
            if d is None:
                continue
            for year in range(first.year, last.year + 1):
                try:
                    when = d.replace(year=year)
                except ValueError:                          # 29/02 em ano não bissexto
                    when = date(year, 2, 28)
                if first <= when <= last:
                    out.append(DayItem(when, kind, text))
    out.sort(key=lambda i: (i.day, i.kind != "birthday", i.kind != "important", i.text.lower()))
    return out


def due_soon(s: Session, entity_id: int, days: int = 1, today: date | None = None) -> list[str]:
    """Para os lembretes: tarefas em aberto atrasadas ou que vencem até `days` dias."""
    today = today or date.today()
    out = []
    for t in list_tasks(s, entity_id, "open", last=today + timedelta(days=days), today=today):
        if t.due_date is None:
            continue
        delta = (t.due_date - today).days
        when = "atrasada" if delta < 0 else "hoje" if delta == 0 else "amanhã" if delta == 1 else f"{t.due_date:%d/%m}"
        out.append(f"Tarefa: {t.title} ({when})")
    return out
