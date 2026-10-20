"""Painel "Caixa × competência" do Dashboard (Fase 3.12): Plus/Pro (D3)."""
from PySide6.QtCore import QDate


def test_painel_caixa_competencia(plus, window, sample):
    window.go_to("dashboard")
    panel = window.page("dashboard").ca_panel
    assert not panel.locked and panel.first.isHidden()                  # este mês: sem as datas
    cash = [lbl.text() for lbl in panel.cells["cash"]]
    assert cash[0] == "R$ 5.000,00"                                     # salário pago neste mês
    assert panel.table.rowCount() >= 28                                 # análise diária do mês
    panel.step.setCurrentIndex(panel.step.findData("month"))
    assert panel.table.rowCount() == 1
    panel.period.setCurrentIndex(panel.period.findData("custom"))
    assert not panel.first.isHidden()
    panel.first.setDate(QDate(2000, 1, 1))
    panel.last.setDate(QDate(2000, 1, 31))
    assert [lbl.text() for lbl in panel.cells["cash"]][0] == "R$ 0,00"
    assert "nada vencido em aberto antes do período" in panel.note.text()


def test_painel_bloqueado_na_free(window):
    window.go_to("dashboard")
    panel = window.page("dashboard").ca_panel
    assert panel.locked and not hasattr(panel, "table")
