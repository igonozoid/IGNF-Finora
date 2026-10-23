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


def test_aniversario_e_data_importante(session, profile):
    from finora.services import contacts
    s, eid = session, profile.id
    contacts.create(s, eid, name="Maria", details={"birthday": "09/10/1980"})
    contacts.create(s, eid, name="Enel", person_type="PJ",
                    details={"important_date": "08/10/2020", "important_label": "Renovação do contrato"})
    contacts.create(s, eid, name="Longe", details={"birthday": "20/12/1990"})
    contacts.create(s, eid, name="Bissexto", details={"birthday": "29/02/2000"})
    today = date(2026, 10, 8)
    r = reminders.check(s, eid, days=1, today=today)
    assert r.dates == ["Renovação do contrato — Enel (hoje)", "Aniversário de Maria (amanhã)"]
    assert not r.empty and "Aniversário de Maria (amanhã)" in r.text("BRL")
    assert reminders.contact_dates(s, eid, days=0, today=date(2026, 2, 28)) == ["Aniversário de Bissexto (hoje)"]
    assert reminders.contact_dates(s, eid, days=3, today=date(2026, 12, 30)) == []
    assert reminders.next_date(date(1990, 1, 2), date(2026, 12, 30)) == date(2027, 1, 2)


def test_aniversario_no_futuro_recusado(session, profile):
    import pytest
    from finora.services import contacts
    with pytest.raises(ValueError, match="futuro"):
        contacts.create(session, profile.id, name="X", details={"birthday": "01/01/2999"})
