from decimal import Decimal as D

from PySide6.QtCore import QDate

from finora.core import db
from finora.services import accounts, entries, fx
from tests.ui.conftest import pump


def test_cotacao_manual_e_transferencia_entre_moedas(plus, window, qtbot):
    with db.Session() as s:
        usd = accounts.create(s, window.profile.id, name="Conta EUA", kind="bank", opening_balance=D("100"),
                              currency="USD")
    window.go_to("settings")
    sec = window.page("settings").currencies
    assert "USD está sem cotação" in sec.warn.text()
    sec.currency.setCurrentIndex(sec.currency.findData("USD"))
    sec.day.setDate(QDate(2020, 1, 1))
    sec.rate.setText("5,25")
    sec.save_btn.click()
    pump(qtbot)
    assert sec.table.item(0, 2).text() == "R$ 5,25" and not sec.warn.isVisible()
    assert "Valores recalculados" in window.statusBar().currentMessage()

    # o cartão da conta mostra quanto vale na moeda principal
    window.go_to("accounts")
    with db.Session() as s:
        acc = next(a for a in accounts.list_accounts(s, window.profile.id) if a.id == usd)
    assert acc.base_balance == D("525.00")

    # transferência do Nubank (BRL) para a conta em dólar: aparece "Valor que chega (US$)"
    window.go_to("entries")
    page = window.page("entries")
    page.new_entry()
    form = page.form
    form.kind_group.button(2).click()
    form.dest.setCurrentIndex(form.dest.findData(usd))
    assert not form.dest_amount.isHidden() and "US$" in form.dest_amount_lbl.label.text()
    form.desc.setText("Câmbio")
    form.amount.setText("525,00")
    form._save()
    assert "quanto chega" in form.error.text()
    form.dest_amount.setText("100,00")
    form._save()
    pump(qtbot)
    with db.Session() as s:
        e = next(x for x in entries.list_entries(s, window.profile.id, year=page.year, month=page.month)
                 if x.description == "Câmbio")
        assert e.dest_amount == D("100.00") and e.dest_currency == "USD"


def test_moedas_bloqueadas_na_free(window):
    sec = window.page("settings").currencies
    assert sec.locked and "Todas as contas" in sec.intro.text()
    with db.Session() as s:
        assert fx.foreign_currencies(s, window.profile.id) == []


def test_cadastrar_outra_moeda_aparece_nas_listas(plus, window, monkeypatch):
    from finora.core import money
    from finora.ui.currencies_section import OtherCurrencyDialog
    sec = window.page("settings").currencies

    def fake_exec(dlg):
        dlg.code.setText("zar")
        dlg.symbol.setText("R")
        dlg.name.setText("Rand sul-africano")
        dlg.add()
        assert dlg.error.isHidden() and dlg.list.rowCount() == 1
        return 0

    monkeypatch.setattr(OtherCurrencyDialog, "exec", fake_exec)
    try:
        sec.other_btn.click()
        assert sec.currency.findData("ZAR") >= 0
        window.go_to("accounts")
        page = window.page("accounts")
        page._set_currency("ZAR")
        assert page.currency_box.currentData() == "ZAR"
    finally:
        money.unregister("ZAR")
