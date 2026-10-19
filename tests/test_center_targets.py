"""Orçamento por centro de custo / projeção por centro de lucro (Fase 3.7, relatório do MCC)."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, cost_centers, entries, reports
from finora.services.entries import EntryData


def test_meta_por_centro(session, profile, plus):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    trator = cost_centers.create(s, eid, "Trator", D("500"), applies_income=False)
    escritorio = cost_centers.create(s, eid, "Escritório", None, applies_income=False)
    vendas = cost_centers.create(s, eid, "Vendas", None, applies_expense=False, projection=D("2000"))
    velho = cost_centers.create(s, eid, "Velho", D("100"))
    cost_centers.update(s, velho, "Velho", D("100"), is_active=False)   # inativo sem lançamento: fora

    def add(kind, amount, month, center, paid=False):
        entries.create(s, eid, EntryData(kind=kind, description="x", amount=D(amount), due_date=date(2026, month, 10),
                                         account_id=bank, cost_center_id=center, paid=paid,
                                         paid_date=date(2026, month, 10) if paid else None))

    add("expense", "600", 1, trator, paid=True)
    add("expense", "1000", 2, trator)
    add("expense", "100", 2, escritorio)
    add("income", "2500", 1, vendas, paid=True)
    add("income", "1000", 3, vendas)
    add("expense", "999", 4, trator)                                    # fora do período
    first, last = date(2026, 1, 1), date(2026, 3, 31)

    exp = {r.name: r for r in reports.center_targets(s, eid, first, last, "expense")}
    assert set(exp) == {"Trator", "Escritório"}                         # Vendas não vale para despesa
    t = exp["Trator"]
    assert (t.monthly, t.months, t.target, t.actual, t.count, t.pct, t.left) == \
        (D("500"), 3, D("1500.00"), D("1600.00"), 2, D("106.7"), D("-100.00"))   # estourou
    assert (exp["Escritório"].target, exp["Escritório"].pct, exp["Escritório"].actual) == (None, None, D("100.00"))
    assert [r.name for r in reports.center_targets(s, eid, first, last, "expense")] == ["Trator", "Escritório"]

    paid = {r.name: r for r in reports.center_targets(s, eid, first, last, "expense", paid_only=True)}
    assert (paid["Trator"].actual, paid["Trator"].pct) == (D("600.00"), D("40.0"))

    (v,) = reports.center_targets(s, eid, first, last, "income")
    assert (v.name, v.target, v.actual, v.pct, v.left) == ("Vendas", D("6000.00"), D("3500.00"), D("58.3"),
                                                            D("2500.00"))
    with pytest.raises(ValueError):
        reports.center_targets(s, eid, first, last, "transfer")
