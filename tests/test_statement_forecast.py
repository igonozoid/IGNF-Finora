"""Extrato de conta com modo previsto (Fase 3.5, do MCC)."""
from datetime import date
from decimal import Decimal as D

from finora.services import accounts, entries, reports
from finora.services.entries import EntryData


def _add(s, eid, account, kind, amount, due, paid=None, desc=None):
    return entries.create(s, eid, EntryData(kind=kind, description=desc or kind, amount=D(amount), due_date=due,
                                            account_id=account, paid=paid is not None, paid_date=paid))


def test_extrato_previsto(session, profile):
    s, eid = session, profile.id
    bank = accounts.create(s, eid, name="Banco Teste", kind="bank", opening_balance=D("1000"))
    _add(s, eid, bank, "expense", "100", date(2026, 5, 20))                                   # atrasado em aberto
    _add(s, eid, bank, "income", "500", date(2026, 6, 10), date(2026, 6, 12), "Recebido")      # realizado
    _add(s, eid, bank, "expense", "200", date(2026, 6, 12), desc="Luz")                        # em aberto no período
    _add(s, eid, bank, "income", "50", date(2026, 7, 5), desc="Depois")                        # vence depois: fora
    first, last = date(2026, 6, 1), date(2026, 6, 30)

    real = reports.account_statement(s, bank, first, last)
    assert (real.opening, real.closing, len(real.lines)) == (D("1000.00"), D("1500.00"), 1)
    assert not real.lines[0].pending

    prev = reports.account_statement(s, bank, first, last, forecast=True)
    assert prev.opening == D("900.00")                                  # o atrasado já entra no saldo anterior
    assert [(x.day, x.description, x.pending, x.balance) for x in prev.lines] == [
        (date(2026, 6, 12), "Recebido", False, D("1400.00")),           # no mesmo dia: realizado antes
        (date(2026, 6, 12), "Luz", True, D("1200.00"))]
    assert prev.closing == D("1200.00")
    same = next(r for r in reports.balances_at(s, eid, last).rows if r.name == "Banco Teste")
    assert same.forecast == prev.closing                                # bate com "Saldos em uma data"
