"""Saldos em uma data: realizado × previsto por conta (Fase 3.2, relatório do MCC)."""
from datetime import date
from decimal import Decimal as D

from finora.services import accounts, entries, reports
from finora.services.entries import EntryData


def _add(s, eid, account, kind, amount, due, paid=None, dest=None):
    return entries.create(s, eid, EntryData(kind=kind, description=kind, amount=D(amount), due_date=due,
                                            account_id=account, dest_account_id=dest, paid=paid is not None,
                                            paid_date=paid))


def test_realizado_e_previsto_numa_data(session, profile):
    s, eid = session, profile.id
    old = [a.name for a in accounts.list_accounts(s, eid)]
    for a in accounts.list_accounts(s, eid):                            # só as contas deste teste
        accounts.set_active(s, a.id, False)
    bank = accounts.create(s, eid, name="Banco Teste", kind="bank", opening_balance=D("1000"))
    cash = accounts.create(s, eid, name="Caixa Teste", kind="cash", opening_balance=D("50"))
    day = date(2026, 6, 30)
    _add(s, eid, bank, "income", "500", date(2026, 6, 10), date(2026, 6, 12))      # recebido antes: realizado
    _add(s, eid, bank, "expense", "200", date(2026, 6, 20), date(2026, 7, 2))      # pago depois da data: previsto
    _add(s, eid, bank, "expense", "80", date(2026, 5, 15))                          # atrasado em aberto: previsto
    _add(s, eid, bank, "income", "300", date(2026, 6, 30))                          # vence no dia: previsto
    _add(s, eid, bank, "income", "999", date(2026, 7, 1))                           # vence depois: fora
    _add(s, eid, bank, "transfer", "100", date(2026, 6, 25), dest=cash)             # transferência em aberto

    rep = reports.balances_at(s, eid, day)
    by = {r.name: r for r in rep.rows}
    b = by["Banco Teste"]
    assert (b.realized, b.to_receive, b.to_pay, b.forecast) == (D("1500.00"), D("300.00"), D("380.00"), D("1420.00"))
    c = by["Caixa Teste"]
    assert (c.realized, c.to_receive, c.to_pay, c.forecast) == (D("50.00"), D("100.00"), D("0.00"), D("150.00"))
    assert (rep.realized, rep.forecast, rep.other_currency) == (D("1550.00"), D("1570.00"), False)

    later = reports.balances_at(s, eid, date(2026, 7, 31))
    assert {r.name: r.realized for r in later.rows}["Banco Teste"] == D("1300.00")      # o pago em 02/07 já entrou

    assert not set(old) & set(by)                                       # inativa só com a opção
    assert set(old) <= {r.name for r in reports.balances_at(s, eid, day, include_inactive=True).rows}


def test_cartao_aparece_mas_fica_fora_do_total(session, profile):
    s, eid = session, profile.id
    card = accounts.create(s, eid, name="Cartão Teste", kind="card", opening_balance=D("0"), closing_day=25, due_day=5,
                           credit_limit=D("3000"))
    before = reports.balances_at(s, eid, date(2026, 6, 30))
    entries.create(s, eid, EntryData(kind="expense", description="Compra", amount=D("250"),
                                     due_date=date(2026, 6, 10), account_id=card))
    rep = reports.balances_at(s, eid, date(2026, 6, 30))
    row = next(r for r in rep.rows if r.name == "Cartão Teste")
    assert row.kind == "card" and row.realized == D("-250.00")         # a compra no cartão já mexeu na conta
    assert (rep.realized, rep.forecast) == (before.realized, before.forecast)
