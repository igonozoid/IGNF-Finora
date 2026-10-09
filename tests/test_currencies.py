from datetime import date
from decimal import Decimal as D

import pytest

from finora.core import money
from finora.services import accounts, currencies, fx


def test_cadastrar_moeda_fora_da_lista(session, profile, plus):
    s = session
    assert "ARS" in money.CURRENCIES and "ZAR" not in money.CURRENCIES
    try:
        assert currencies.add(s, "zar", "R", "Rand sul-africano") == "ZAR"
        assert money.symbol("ZAR") == "R" and money.fmt(D("10"), "ZAR").endswith("10,00")
        with pytest.raises(ValueError, match="já está"):
            currencies.add(s, "ZAR", "R", "x")
        with pytest.raises(ValueError, match="3 letras"):
            currencies.add(s, "ZA", "R", "x")
        acc = accounts.create(s, profile.id, name="Conta África", kind="bank", currency="ZAR",
                              opening_balance=D("100"))
        fx.set_rate(s, profile.id, "ZAR", date(2026, 10, 1), D("0.30"))
        with pytest.raises(ValueError, match="em uso"):
            currencies.remove(s, "ZAR")
        money.unregister("ZAR")
        assert currencies.load(s) == 1 and "ZAR" in money.CURRENCIES     # volta ao abrir o app
        assert acc
    finally:
        money.unregister("ZAR")
    assert "USD" in money.BUILTIN and money.unregister("USD") is None and "USD" in money.CURRENCIES
