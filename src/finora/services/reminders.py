"""Lembretes: contas a pagar atrasadas e as que vencem nos próximos dias, e aniversários e datas importantes
dos contatos."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finora.core import money
from finora.models import Contact, Entry
from finora.services import scope

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Reminder:
    overdue: int
    overdue_total: Decimal
    soon: int                    # vencem de hoje até `days` dias
    soon_total: Decimal
    days: int
    first: list[str]             # até 3 descrições, as mais urgentes
    dates: list[str] = field(default_factory=list)      # "Aniversário de Maria (hoje)"…

    @property
    def empty(self) -> bool:
        return not (self.overdue or self.soon or self.dates)

    def text(self, currency: str) -> str:
        parts = []
        if self.overdue:
            parts.append(f"{self.overdue} {'conta atrasada' if self.overdue == 1 else 'contas atrasadas'} "
                         f"({money.fmt(self.overdue_total, currency)})")
        if self.soon:
            when = "hoje" if self.days == 0 else "até amanhã" if self.days == 1 else f"nos próximos {self.days} dias"
            parts.append(f"{self.soon} {'vence' if self.soon == 1 else 'vencem'} {when} "
                         f"({money.fmt(self.soon_total, currency)})")
        text = " · ".join(parts)
        if self.first:
            text += "\n" + ", ".join(self.first) + ("…" if self.overdue + self.soon > len(self.first) else "")
        if self.dates:
            text = (text + "\n" if text else "") + " · ".join(self.dates)
        return text


def check(s: Session, entity_id: int, days: int = 1, today: date | None = None) -> Reminder:
    """Despesas em aberto: atrasadas e as que vencem até `days` dias (0 = só hoje). Compras no cartão ficam na
    fatura, que aparece como conta do cartão. Junta as datas dos contatos no mesmo período."""
    today = today or date.today()
    q = (select(Entry.due_date, Entry.description, Entry.base_amount)
         .where(Entry.entity_id == entity_id, Entry.kind == "expense", Entry.status == "pending",
                Entry.due_date <= today + timedelta(days=days))
         .order_by(Entry.due_date, Entry.id))
    over_n = soon_n = 0
    over_t = soon_t = ZERO
    first = []
    for due, desc, amount in s.execute(q):
        if due < today:
            over_n += 1
            over_t += Decimal(amount)
        else:
            soon_n += 1
            soon_t += Decimal(amount)
        if len(first) < 3:
            first.append(desc or "Sem descrição")
    dates = contact_dates(s, entity_id, days, today)
    from finora.services import agenda, modules
    if modules.is_on(s, entity_id, "agenda"):
        dates += agenda.due_soon(s, entity_id, days, today)
    return Reminder(over_n, over_t, soon_n, soon_t, days, first, dates)


def next_date(d: date, today: date) -> date:
    """Próxima vez que o dia/mês de `d` acontece a partir de hoje (29/02 vira 28/02 em ano não bissexto)."""
    for year in (today.year, today.year + 1):
        try:
            when = d.replace(year=year)
        except ValueError:
            when = date(year, 2, 28)
        if when >= today:
            return when
    return when


def contact_dates(s: Session, entity_id: int, days: int = 1, today: date | None = None) -> list[str]:
    """Aniversários e datas importantes dos contatos de hoje até `days` dias, as mais próximas primeiro."""
    today = today or date.today()
    found = []
    q = select(Contact.name, Contact.birthday, Contact.important_date, Contact.important_label).where(
        scope.contacts(entity_id), Contact.birthday.is_not(None) | Contact.important_date.is_not(None))
    for name, birthday, important, label in s.execute(q):
        for d, what in ((birthday, f"Aniversário de {name}"), (important, f"{label or 'Data importante'} — {name}")):
            if d is not None:
                when = next_date(d, today)
                if (when - today).days <= days:
                    found.append((when, what))
    out = []
    for when, what in sorted(found):
        delta = (when - today).days
        out.append(f"{what} ({'hoje' if delta == 0 else 'amanhã' if delta == 1 else when.strftime('%d/%m')})")
    return out
