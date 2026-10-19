"""Extrato de fechamento de caixa na tela de Relatórios (Fase 3.4): Plus/Pro (D3)."""


def test_fechamento_de_caixa_na_tela(plus, window, sample):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "cash_closing"))
    view = rp.views["cash_closing"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    first = [view.table.item(0, c).text() for c in range(view.table.columnCount())]
    assert first[2] == "Saldo anterior (todas as contas)"
    salario = next(r for r in range(view.table.rowCount()) if view.table.item(r, 2).text() == "Salário")
    assert view.table.item(salario, 1).text() == "Nubank" and view.table.item(salario, 4).text() == "R$ 5.000,00"
    assert "Saldo final" in view.footer.text()
    assert view.export_sheet().title == "Fechamento de caixa"


def test_fechamento_de_caixa_bloqueado_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "cash_closing")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
