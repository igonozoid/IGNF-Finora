from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, entries, fx, period_lock
from finora.services.entries import EntryData
from finora.services.period_lock import PeriodLockedError


def _e(s, eid, when, desc="Luz", paid=False):
    bank = accounts.list_accounts(s, eid)[0].id
    return entries.create(s, eid, EntryData(kind="expense", description=desc, amount=D("100"), due_date=when,
                                            account_id=bank, paid=paid, paid_date=when if paid else None))[0]


def test_fechar_impede_criar_alterar_e_excluir(session, profile):
    s, eid = session, profile.id
    ago = _e(s, eid, date(2026, 8, 10))
    period_lock.set_lock(s, eid, date(2026, 8, 31))
    assert period_lock.is_locked(s, eid, date(2026, 8, 31)) and not period_lock.is_locked(s, eid, date(2026, 9, 1))
    with pytest.raises(PeriodLockedError, match="31/08/2026 está fechado"):
        _e(s, eid, date(2026, 8, 20))
    s.rollback()
    bank = accounts.list_accounts(s, eid)[0].id
    with pytest.raises(PeriodLockedError):
        entries.update(s, ago, EntryData(kind="expense", description="Luz (corrigida)", amount=D("120"),
                                         due_date=date(2026, 8, 10), account_id=bank))
    with pytest.raises(PeriodLockedError):        # mover de um mês aberto para dentro do fechado também não
        set_id = _e(s, eid, date(2026, 9, 5))
        entries.update(s, set_id, EntryData(kind="expense", description="Luz", amount=D("100"),
                                            due_date=date(2026, 8, 30), account_id=bank))
    s.rollback()
    with pytest.raises(PeriodLockedError):
        entries.delete(s, ago)
    s.rollback()
    _e(s, eid, date(2026, 9, 1))                  # setembro está aberto


def test_pagar_depois_conta_antiga_pode(session, profile):
    s, eid = session, profile.id
    ago = _e(s, eid, date(2026, 8, 10))
    pago = _e(s, eid, date(2026, 8, 5), "Água", paid=True)
    period_lock.set_lock(s, eid, date(2026, 8, 31))
    entries.set_paid(s, ago, True, date(2026, 9, 3))          # pagamento em data aberta: ok
    assert entries.get(s, ago).is_paid
    with pytest.raises(PeriodLockedError):                   # desfazer pagamento feito no período fechado: não
        entries.set_paid(s, pago, False)
    s.rollback()
    with pytest.raises(PeriodLockedError):                   # pagar com data dentro do fechado: não
        entries.set_paid(s, ago, False)
        entries.set_paid(s, ago, True, date(2026, 8, 31))


def test_reabrir_e_validacoes(session, profile, plus):
    s, eid = session, profile.id
    ago = _e(s, eid, date(2026, 8, 10))
    with pytest.raises(ValueError, match="já passaram"):
        period_lock.set_lock(s, eid, date(2999, 1, 1))
    period_lock.set_lock(s, eid, date(2026, 8, 31))
    accounts.create(s, eid, name="EUA", kind="bank", opening_balance=D("0"), currency="USD")
    with pytest.raises(ValueError, match="fechado"):
        fx.set_rate(s, eid, "USD", date(2026, 8, 1), D("5"))
    fx.set_rate(s, eid, "USD", date(2026, 9, 1), D("5"))     # depois do fechamento: ok (recalcula sem travar)
    period_lock.set_lock(s, eid, None)
    entries.delete(s, ago)
