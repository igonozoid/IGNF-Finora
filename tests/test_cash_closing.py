"""Extrato de fechamento de caixa (Fase 3.4, relatório do MCC)."""
from datetime import date
from decimal import Decimal as D

from finora.services import accounts, entries, reports
from finora.services.entries import EntryData


def _add(s, eid, account, kind, amount, due, paid=None, dest=None, desc=None):
    return entries.create(s, eid, EntryData(kind=kind, description=desc or kind, amount=D(amount), due_date=due,
                                            account_id=account, dest_account_id=dest, paid=paid is not None,
                                            paid_date=paid))


def test_fechamento_de_caixa(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id                         # "Banco", R$ 100
    cash = accounts.create(s, eid, name="Caixa Teste", kind="cash", opening_balance=D("50"))
    card = accounts.create(s, eid, name="Cartão Teste", kind="card", opening_balance=D("0"), closing_day=25,
                           due_day=5, credit_limit=D("3000"))
    _add(s, eid, bank, "income", "1000", date(2026, 5, 20), date(2026, 5, 20))       # antes: saldo anterior
    _add(s, eid, bank, "expense", "300", date(2026, 6, 5), date(2026, 6, 5), desc="Aluguel")
    _add(s, eid, cash, "income", "200", date(2026, 6, 10), date(2026, 6, 10), desc="Venda")
    _add(s, eid, bank, "transfer", "150", date(2026, 6, 12), date(2026, 6, 12), dest=cash)   # entre contas
    _add(s, eid, card, "expense", "80", date(2026, 6, 15), desc="Compra no cartão")          # cartão: fora
    _add(s, eid, bank, "transfer", "80", date(2026, 6, 20), date(2026, 6, 20), dest=card, desc="Fatura")
    _add(s, eid, bank, "expense", "999", date(2026, 6, 25))                                  # em aberto: fora
    first, last = date(2026, 6, 1), date(2026, 6, 30)

    rep = reports.cash_closing(s, eid, first, last)
    assert rep.accounts == ["Banco", "Caixa Teste"]                      # sem cartão
    assert rep.opening == D("1150.00")
    assert [(x.day.day, x.account, x.description, x.inflow, x.outflow, x.balance) for x in rep.lines] == [
        (5, "Banco", "Aluguel", D("0.00"), D("300"), D("850.00")),
        (10, "Caixa Teste", "Venda", D("200"), D("0.00"), D("1050.00")),
        (20, "Banco", "Fatura", D("0.00"), D("80"), D("970.00"))]      # pagar a fatura sai do caixa
    assert (rep.inflow, rep.outflow, rep.closing) == (D("200"), D("380"), D("970.00"))

    with_internal = reports.cash_closing(s, eid, first, last, internal=True)
    moved = [x for x in with_internal.lines if x.internal]
    assert [(x.account, x.inflow, x.outflow) for x in moved] == [("Banco", D("0.00"), D("150")),
                                                                  ("Caixa Teste", D("150"), D("0.00"))]
    assert with_internal.closing == rep.closing and moved[0].balance == moved[1].balance == D("1050.00")
    total = sum((r.realized for r in reports.balances_at(s, eid, last).rows if r.kind != "card"), D(0))
    assert total == rep.closing                                         # bate com "Saldos em uma data"
