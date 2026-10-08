from datetime import date
from decimal import Decimal as D

from finora.services import accounts, entries, reminders
from finora.services.entries import EntryData


def test_lembrete_atrasadas_e_a_vencer(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    today = date(2026, 10, 8)
    for desc, due, val in (("Luz", date(2026, 10, 5), "100"), ("Água", date(2026, 10, 8), "50"),
                           ("Internet", date(2026, 10, 9), "120"), ("Aluguel", date(2026, 10, 20), "1500")):
        entries.create(s, eid, EntryData(kind="expense", description=desc, amount=D(val), due_date=due,
                                         account_id=bank))
    entries.create(s, eid, EntryData(kind="income", description="Salário", amount=D("5000"),
                                     due_date=date(2026, 10, 8), account_id=bank))      # a receber não avisa
    r = reminders.check(s, eid, days=1, today=today)
    assert (r.overdue, r.overdue_total, r.soon, r.soon_total) == (1, D("100.00"), 2, D("170.00"))
    assert r.first == ["Luz", "Água", "Internet"]
    text = r.text("BRL")
    assert "1 conta atrasada" in text and "2 vencem até amanhã" in text
    assert reminders.check(s, eid, days=0, today=today).soon == 1
    assert reminders.check(s, eid, days=0, today=date(2026, 10, 1)).empty
