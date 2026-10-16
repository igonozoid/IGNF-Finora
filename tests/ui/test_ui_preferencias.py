"""Preferências de lançamento por entidade (como o FConfigConta do MCC): conta padrão, campo inicial e saldos."""
from decimal import Decimal as D

from finora.core import db, settings
from finora.services import accounts


def test_preferencias_por_entidade(window, qtbot):
    with db.Session() as s:
        caixa = accounts.create(s, window.profile.id, name="Caixa", kind="cash", opening_balance=D(0))
    window.go_to("settings")
    page = window.page("settings")
    assert page.pref_account.currentData() is None and page.pref_account.findData(caixa) >= 0   # recarregou
    page.pref_account.setCurrentIndex(page.pref_account.findData(caixa))
    page.pref_first.setCurrentIndex(page.pref_first.findData("amount"))
    page.pref_balances.setChecked(False)
    prefs = settings.get_entry_prefs(window.profile.id)
    assert (prefs.default_account, prefs.first_field, prefs.show_balances) == (caixa, "amount", False)

    window.go_to("entries")                                             # lançamento novo: Caixa e cursor no valor
    entries_page = window.page("entries")
    window.new_entry()
    qtbot.wait(20)
    form = entries_page.form
    assert form.account.currentData() == caixa
    assert form.focusWidget() is form.amount or entries_page.focusWidget() is form.amount
    form.cancel_btn.click()

    window.go_to("dashboard")                                           # saldos escondidos
    dash = window.page("dashboard")
    assert dash.k_balance.value.text() == "•••" and dash.acc_box.isHidden()
    settings.set_entry_prefs(window.profile.id, settings.EntryPrefs(None, "description", True))
    dash.refresh()
    assert dash.k_balance.value.text() != "•••" and not dash.acc_box.isHidden()


def test_preferencia_invalida_e_padrao(window):
    import pytest
    assert settings.get_entry_prefs(999) == settings.EntryPrefs()
    with pytest.raises(ValueError):
        settings.set_entry_prefs(1, settings.EntryPrefs(None, "cor", True))
