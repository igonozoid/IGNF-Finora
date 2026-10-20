"""Dashboard: caixa × competência e análise linear (Fase 3.12, do MCC)."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, dashboard, entries
from finora.services.entries import EntryData


def _add(s, eid, bank, kind, amount, due, paid=None):
    return entries.create(s, eid, EntryData(kind=kind, description=kind, amount=D(amount), due_date=due,
                                            account_id=bank, paid=paid is not None, paid_date=paid))


def test_caixa_x_competencia(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    _add(s, eid, bank, "income", "1000", date(2026, 6, 10), date(2026, 6, 10))     # nos dois
    _add(s, eid, bank, "expense", "300", date(2026, 5, 25), date(2026, 6, 3))      # caixa sim, competência não
    _add(s, eid, bank, "expense", "200", date(2026, 6, 20))                         # competência sim, caixa não
    _add(s, eid, bank, "income", "400", date(2026, 6, 28), date(2026, 7, 2))       # competência sim; pago depois
    _add(s, eid, bank, "expense", "80", date(2026, 5, 15))                          # vencido em aberto
    _add(s, eid, bank, "income", "50", date(2026, 4, 30))                           # vencido em aberto (a receber)
    first, last = date(2026, 6, 1), date(2026, 6, 30)

    ca = dashboard.cash_vs_accrual(s, eid, first, last)
    assert (ca.cash.income, ca.cash.expense, ca.cash.result) == (D("1000.00"), D("300.00"), D("700.00"))
    assert (ca.accrual.income, ca.accrual.expense, ca.accrual.result) == (D("1400.00"), D("200.00"), D("1200.00"))
    assert (ca.overdue.income, ca.overdue.expense, ca.overdue.count) == (D("50.00"), D("80.00"), 2)
    with_late = dashboard.cash_vs_accrual(s, eid, first, last, overdue=True)
    assert (with_late.accrual.income, with_late.accrual.expense) == (D("1450.00"), D("280.00"))
    assert with_late.cash == ca.cash                                    # o caixa não muda


def test_analise_linear(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    _add(s, eid, bank, "income", "1000", date(2026, 6, 1), date(2026, 6, 1))
    _add(s, eid, bank, "expense", "300", date(2026, 6, 3), date(2026, 6, 3))
    _add(s, eid, bank, "expense", "200", date(2026, 6, 9))                          # em aberto
    first, last = date(2026, 6, 1), date(2026, 6, 14)

    days = dashboard.linear(s, eid, first, last, "day", "cash")
    assert len(days) == 14 and days[0].label == "01/06"                 # com os dias vazios
    assert [(r.income, r.expense, r.cumulative) for r in days[:3]] == [
        (D("1000.00"), D("0.00"), D("1000.00")), (D("0.00"), D("0.00"), D("1000.00")),
        (D("0.00"), D("300.00"), D("700.00"))]
    weeks = dashboard.linear(s, eid, first, last, "week", "accrual")    # 01/06/2026 é segunda
    assert [(r.label, r.result, r.cumulative) for r in weeks] == [
        ("01/06 a 07/06", D("700.00"), D("700.00")), ("08/06 a 14/06", D("-200.00"), D("500.00"))]
    months = dashboard.linear(s, eid, date(2026, 5, 1), date(2026, 7, 31), "month", "cash")
    assert [(r.label, r.result) for r in months] == [("mai/2026", D("0.00")), ("jun/2026", D("700.00")),
                                                      ("jul/2026", D("0.00"))]
    with pytest.raises(ValueError):
        dashboard.linear(s, eid, first, last, "hour")


def test_periodos():
    today = date(2026, 10, 21)                                          # quarta-feira
    assert dashboard.ca_range("today", today) == (today, today)
    assert dashboard.ca_range("week", today) == (date(2026, 10, 19), date(2026, 10, 25))
    assert dashboard.ca_range("month", today) == (date(2026, 10, 1), date(2026, 10, 31))
    assert dashboard.ca_range("month", date(2026, 12, 5)) == (date(2026, 12, 1), date(2026, 12, 31))
