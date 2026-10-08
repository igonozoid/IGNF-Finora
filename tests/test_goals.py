from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, entries, goals
from finora.services.entries import EntryData


def test_meta_com_valor_guardado_e_com_conta(session, profile):
    s, eid = session, profile.id
    gid = goals.create(s, eid, name="Viagem", target=D("6000"), due_date=date(2027, 4, 30))
    assert goals.add_saving(s, gid, D("1500")) == D("1500.00")
    g = goals.list_goals(s, eid)[0]
    assert (g.pct, g.missing) == (25, D("4500.00"))
    assert g.months_left(date(2026, 10, 8)) == 6 and g.monthly(date(2026, 10, 8)) == D("750.00")
    with pytest.raises(ValueError, match="negativo"):
        goals.add_saving(s, gid, D("-2000"))
    with pytest.raises(ValueError, match="Já existe"):
        goals.create(s, eid, name="viagem", target=D("1"))
    with pytest.raises(ValueError, match="quanto"):
        goals.create(s, eid, name="Carro", target=D("0"))

    bank = accounts.list_accounts(s, eid)[0]
    rid = goals.create(s, eid, name="Reserva", target=D("200"), account_id=bank.id)
    reserva = next(x for x in goals.list_goals(s, eid) if x.id == rid)
    assert reserva.current == bank.balance and reserva.account == bank.name
    entries.create(s, eid, EntryData(kind="income", description="Bônus", amount=D("500"), due_date=date(2026, 10, 1),
                                     account_id=bank.id, paid=True, paid_date=date(2026, 10, 1)))
    reserva = next(x for x in goals.list_goals(s, eid) if x.id == rid)
    assert reserva.current == bank.balance + D("500") and reserva.done and reserva.monthly() is None
    with pytest.raises(ValueError, match="saldo da conta"):
        goals.add_saving(s, rid, D("10"))
    goals.update(s, rid, name="Reserva", target=D("200"), account_id=bank.id, is_active=False)
    assert [x.name for x in goals.list_goals(s, eid)] == ["Viagem"]
    goals.delete(s, gid)
    assert goals.list_goals(s, eid) == []
