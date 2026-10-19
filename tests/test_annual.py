"""Demonstrativo anual por categoria, contato, centro de custo ou conta (Fase 3.6, relatório do MCC)."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, categories, cost_centers, entries, reports
from finora.services.entries import EntryData

YEAR = [(2026, m) for m in range(1, 13)]


def test_demonstrativo_anual(session, profile, plus):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id                         # "Banco"
    cash = accounts.create(s, eid, name="Caixa", kind="cash", opening_balance=D("0"))
    cc = cost_centers.create(s, eid, "Trator", None)
    luz = next(cid for cid, label in categories.choices(s, eid, "expense") if label.endswith("› Luz"))

    def add(kind, amount, month, account=bank, contact=None, cat=None, center=None, status_paid=False):
        entries.create(s, eid, EntryData(kind=kind, description="x", amount=D(amount), due_date=date(2026, month, 10),
                                         account_id=account, contact=contact, category_id=cat, cost_center_id=center,
                                         paid=status_paid, paid_date=date(2026, month, 10) if status_paid else None))

    add("expense", "100", 1, contact="Enel", cat=luz, center=cc)
    add("expense", "150", 3, contact="Enel", cat=luz)
    add("expense", "60", 3, account=cash, contact="Posto")
    add("income", "1000", 2, contact="Cliente", status_paid=True)
    add("income", "500", 2, account=cash)
    entries.create(s, eid, EntryData(kind="expense", description="ano que vem", amount=D("9"),
                                     due_date=date(2027, 1, 10), account_id=bank))   # fora do ano

    by_contact = {(r.category, r.kind): r for r in reports.by_month(s, eid, YEAR, "contact")}
    enel = by_contact[("Enel", "expense")]
    assert (enel.values[0], enel.values[2], enel.total, enel.average) == (D("100.00"), D("150.00"), D("250.00"),
                                                                           D("20.83"))
    assert by_contact[("Sem contato", "income")].total == D("500.00")
    assert [r.kind for r in reports.by_month(s, eid, YEAR, "contact")][:2] == ["income", "income"]   # receitas 1º

    by_cc = {(r.category, r.kind): r.total for r in reports.by_month(s, eid, YEAR, "cost_center")}
    assert by_cc[("Trator", "expense")] == D("100.00") and by_cc[("Sem centro de custo", "expense")] == D("210.00")
    by_acc = {(r.category, r.kind): r.total for r in reports.by_month(s, eid, YEAR, "account")}
    assert (by_acc[("Banco", "expense")], by_acc[("Caixa", "expense")], by_acc[("Caixa", "income")]) == \
        (D("250.00"), D("60.00"), D("500.00"))
    by_cat = {(r.group, r.category): r.total for r in reports.by_month(s, eid, YEAR, "category")}
    assert by_cat[("Moradia", "Luz")] == D("250.00")
    assert reports.category_by_month(s, eid, YEAR) == reports.by_month(s, eid, YEAR)   # o comparativo continua igual
    with pytest.raises(ValueError):
        reports.by_month(s, eid, YEAR, "cidade")
