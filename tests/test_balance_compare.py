"""Comparativo de saldos entre duas datas (Fase 3.3, relatório do MCC)."""
from datetime import date
from decimal import Decimal as D

from finora.services import accounts, entries, reports
from finora.services.entries import EntryData


def _add(s, eid, account, kind, amount, due, paid=None, dest=None):
    return entries.create(s, eid, EntryData(kind=kind, description=kind, amount=D(amount), due_date=due,
                                            account_id=account, dest_account_id=dest, paid=paid is not None,
                                            paid_date=paid))


def test_comparativo_entre_duas_datas(session, profile):
    s, eid = session, profile.id
    for a in accounts.list_accounts(s, eid):
        accounts.set_active(s, a.id, False)
    bank = accounts.create(s, eid, name="Banco Teste", kind="bank", opening_balance=D("1000"))
    cash = accounts.create(s, eid, name="Caixa Teste", kind="cash", opening_balance=D("0"))
    _add(s, eid, bank, "income", "400", date(2026, 5, 20), date(2026, 5, 20))      # antes da 1ª data
    _add(s, eid, bank, "income", "1000", date(2026, 6, 10), date(2026, 6, 10))     # no intervalo: entrada
    _add(s, eid, bank, "expense", "300", date(2026, 6, 15), date(2026, 6, 30))     # no intervalo (2ª data incl.)
    _add(s, eid, bank, "transfer", "200", date(2026, 6, 20), date(2026, 6, 20), dest=cash)
    _add(s, eid, bank, "expense", "50", date(2026, 6, 25), date(2026, 7, 1))       # pago depois: fora
    _add(s, eid, bank, "expense", "70", date(2026, 6, 26))                          # em aberto: fora (só realizado)

    rep = reports.compare_balances(s, eid, date(2026, 6, 30), date(2026, 5, 31))   # datas invertidas: ordena
    assert (rep.first, rep.last) == (date(2026, 5, 31), date(2026, 6, 30))
    by = {r.name: r for r in rep.rows}
    b = by["Banco Teste"]
    assert (b.start, b.inflow, b.outflow, b.end, b.change, b.change_pct) == \
        (D("1400.00"), D("1000.00"), D("500.00"), D("1900.00"), D("500.00"), D("35.7"))
    c = by["Caixa Teste"]
    assert (c.start, c.inflow, c.outflow, c.end, c.change_pct) == (D("0.00"), D("200.00"), D("0.00"), D("200.00"), None)
    assert (rep.start, rep.inflow, rep.outflow, rep.end, rep.change) == \
        (D("1400.00"), D("1200.00"), D("500.00"), D("2100.00"), D("700.00"))   # transferência entra e sai

    same = reports.balances_at(s, eid, date(2026, 6, 30))               # bate com "Saldos em uma data"
    assert {r.name: r.realized for r in same.rows} == {r.name: r.end for r in rep.rows}
