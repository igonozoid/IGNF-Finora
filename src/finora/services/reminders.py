"""Lembretes de vencimento: o que avisar (contas a pagar atrasadas e as que vencem nos próximos dias)."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finora.core import money
from finora.models import Entry

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Reminder:
    overdue: int
    overdue_total: Decimal
    soon: int                    # vencem de hoje até `days` dias
    soon_total: Decimal
    days: int
    first: list[str]             # até 3 descrições, as mais urgentes

    @property
    def empty(self) -> bool:
        return not (self.overdue or self.soon)

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
        return text


def check(s: Session, entity_id: int, days: int = 1, today: date | None = None) -> Reminder:
    """Despesas em aberto: atrasadas e as que vencem até `days` dias (0 = só hoje). Compras no cartão ficam na
    fatura, que aparece como conta do cartão."""
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
    return Reminder(over_n, over_t, soon_n, soon_t, days, first)
