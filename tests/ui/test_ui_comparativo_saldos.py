"""Comparativo de saldos entre duas datas na tela de Relatórios (Fase 3.3): Plus/Pro (D3)."""
from PySide6.QtCore import QDate


def test_comparativo_de_saldos(plus, window, sample):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "balance_compare"))
    view = rp.views["balance_compare"]
    view.first.setDate(QDate(2000, 1, 1))
    view.last.setDate(QDate(2000, 12, 31))
    assert view.table.horizontalHeaderItem(1).text() == "SALDO EM 01/01/00"
    assert view.table.horizontalHeaderItem(4).text() == "SALDO EM 31/12/00"
    first = [view.table.item(0, c).text() for c in range(view.table.columnCount())]
    assert first[0] == "Nubank" and first[1] == first[4] and first[2] == first[3] == ""   # nada no intervalo
    assert view.table.item(view.table.rowCount() - 1, 0).text() == "Total (sem cartões)"
    view.last.setDate(QDate.currentDate().addDays(1))                   # agora o salário do mês entra
    nubank = [view.table.item(0, c).text() for c in range(view.table.columnCount())]
    assert nubank[2] == "R$ 5.000,00" and nubank[1] != nubank[4]       # salário pago hoje: entrada
    assert view.export_sheet().subtitle.startswith("01/01/2000 a ")


def test_comparativo_bloqueado_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "balance_compare")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
