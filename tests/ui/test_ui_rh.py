"""Tela RH (módulo "hr", decisão D4)."""
from decimal import Decimal as D

from PySide6.QtWidgets import QDialog, QInputDialog

from finora.core import db
from finora.services import hr, modules
from finora.ui import hr_page


def _ligar(window):
    with db.Session() as s:
        modules.set_enabled(s, window.profile.id, "hr", True)
    window._apply_access()


def test_rh_novo_funcionario_perfil_e_historico(window, monkeypatch):
    assert "hr" not in window.visible_keys
    _ligar(window)
    window.go_to("hr")
    page = window.page("hr")
    assert "Nenhum funcionário" in page.empty.text()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Ana Diarista", True)))
    page.new_btn.click()
    assert [e.name for e in page.items] == ["Ana Diarista"]
    panel = page.panel
    assert not panel.body.isHidden() and panel.title.text() == "Ana Diarista"
    panel.job.setText("Diarista")
    panel.inss.setText("8")
    panel.initial.setText("1.200,00")
    panel.save_btn.click()
    assert not panel.error.isVisible(), panel.error.text()
    with db.Session() as s:
        assert hr.get_profile(s, panel.contact_id)["inss_rate"] == D("0.0800")
    assert "Custo total" in panel.cost_lbl.text() and "R$ 1.200,00" in page.table.item(0, 4).text()

    def run(dlg):
        assert dlg.kind == "benefit"
        dlg.fields["name"].setText("Unimed")
        dlg.fields["amount"].setText("300")
        dlg.ok_btn.click()
        return QDialog.Accepted
    monkeypatch.setattr(hr_page.RecordDialog, "exec", run)
    panel.add_kind.setCurrentIndex(panel.add_kind.findData("benefit"))
    panel.add_btn.click()
    assert panel.history.rowCount() == 1 and panel.history.item(0, 0).text() == "Benefício"
    assert "Folha do mês R$ 1.500,00" in page.footer.text()


def test_historico_mostra_erro_no_dialogo(window, monkeypatch):
    _ligar(window)
    with db.Session() as s:
        hr.add_employee(s, window.profile.id, "João")
    window.go_to("hr")
    page = window.page("hr")
    page.table.selectRow(0)
    page._selected(0)

    def run(dlg):
        dlg.ok_btn.click()                                          # salário sem valor
        assert "data e do valor" in dlg.error.text()
        return QDialog.Rejected
    monkeypatch.setattr(hr_page.RecordDialog, "exec", run)
    page.panel.add_kind.setCurrentIndex(0)
    page.panel.add_btn.click()
    assert page.panel.history.rowCount() == 0
