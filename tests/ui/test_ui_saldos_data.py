"""Relatório "Saldos em uma data" na tela de Relatórios (Fase 3.2): Plus/Pro (D3)."""
from PySide6.QtCore import QDate


def _open(window):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "balances_at"))
    return rp.views["balances_at"]


def test_saldos_em_uma_data(plus, window, sample):
    view = _open(window)
    table = [[view.table.item(r, c).text() for c in range(view.table.columnCount())]
             for r in range(view.table.rowCount())]
    nubank = next(r for r in table if r[0] == "Nubank")
    assert nubank[1] == "Conta no banco" and nubank[2] and nubank[5]
    assert table[-1][0] == "Total (sem cartões)"
    assert "Realizado" in view.footer.text() and "Previsto" in view.footer.text()

    view.day.setDate(QDate(2000, 1, 1))                                 # antes de tudo: só o saldo inicial
    first = [view.table.item(0, c).text() for c in range(view.table.columnCount())]
    assert first[0] == "Nubank" and first[2] == first[5] and first[3] == first[4] == ""
    sheet = view.export_sheet()
    assert sheet.title == "Saldos em uma data" and sheet.subtitle == "Em 01/01/2000"


def test_saldos_bloqueado_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "balances_at")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
