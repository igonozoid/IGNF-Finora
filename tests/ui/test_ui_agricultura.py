from datetime import date
from decimal import Decimal as D

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog

from finora.core import db
from finora.services import modules, rural, stock


def _preparar(window):
    eid = window.profile.id
    with db.Session() as s:
        modules.set_enabled(s, eid, "rural", True)
        adubo = stock.create_item(s, eid, name="Adubo NPK", kind="input", unit="kg")
        azeitona = stock.create_item(s, eid, name="Azeitona", kind="input", unit="kg")
        stock.move(s, eid, item_id=adubo, kind="in", quantity="1000", day=date(2026, 1, 5), unit_cost="3")
    window._apply_access()
    return adubo, azeitona


def _pick(box, item_id):
    box.pick.setCurrentIndex(box.pick.findData(item_id))


def test_cadastro_atividade_colheita_e_custo_por_area(window, monkeypatch):
    from finora.ui.rural_dialogs import ActivityDialog, AreaDialog, FarmDialog
    adubo, azeitona = _preparar(window)
    assert {"stock", "rural"} <= set(window.visible_keys)
    window.go_to("rural")
    page = window.page("rural")
    assert "Nova propriedade" in page.empty.text()

    def fazenda(dlg):
        dlg.name.setText("Singolare")
        dlg._ok()
        return QDialog.Accepted

    monkeypatch.setattr(FarmDialog, "exec", fazenda)
    page.new_farm()
    assert page.farm.currentText() == "Singolare"

    def area(dlg):
        dlg.name.setText("Pomar 1")
        dlg.kind.setCurrentIndex(dlg.kind.findData("orchard"))
        dlg.crop.setText("Oliveira arbequina")
        dlg.hectares.setText("10")
        dlg._ok()
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(AreaDialog, "exec", area)
    page.open_area(None)

    def adubacao(dlg):
        dlg.day.setDate(QDate(2026, 2, 1))
        dlg.kind.setCurrentIndex(dlg.kind.findData("fertilizing"))
        assert dlg.harvest.isHidden()
        _pick(dlg.inputs, adubo)
        dlg.inputs.qty.setText("400")
        dlg.inputs.add_line()
        dlg.other.setText("300")
        assert "1.500,00" in dlg.cost_lbl.text()
        dlg.save()
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(ActivityDialog, "exec", adubacao)
    page.new_btn.click()
    assert "Adubação registrada" in window.statusBar().currentMessage()

    def colheita(dlg):
        dlg.day.setDate(QDate(2026, 4, 10))
        dlg.kind.setCurrentIndex(dlg.kind.findData("harvest"))
        assert not dlg.harvest.isHidden()
        _pick(dlg.harvest, azeitona)
        dlg.harvest.qty.setText("3000")
        dlg.harvest.add_line()
        assert dlg.hcost.placeholderText() == "1.500,00"
        assert dlg.harvest.table.item(0, 3).text() == "R$ 0,50"
        dlg.save()
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(ActivityDialog, "exec", colheita)
    page.new_btn.click()
    page.period.setCurrentIndex(page.period.findData("all"))
    assert [r.kind for r in page.rows] == ["harvest", "fertilizing"]
    with db.Session() as s:
        assert stock.balance(s, window.profile.id, azeitona) == D("3000")
        assert stock.average_cost(s, window.profile.id, azeitona) == D("0.5")
    page.group.button(2).click()                                      # custo por área
    row = page.rows[0]
    assert (row.total, row.per_ha, row.harvested) == (D("1500.00"), D("150.00"), "Azeitona 3.000 kg")
    assert "Custo por área" in page.export_sheet().title
    page.group.button(1).click()                                      # áreas
    assert page.rows[0].pending_cost == D("0")

    def excluir(dlg):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        dlg.do_delete()
        return QDialog.Accepted

    page.group.button(0).click()
    monkeypatch.setattr(ActivityDialog, "exec", excluir)
    page.open_activity(0)                                             # a colheita (mais recente)
    with db.Session() as s:
        assert stock.balance(s, window.profile.id, azeitona) == D("0")
        assert rural.areas(s, window.profile.id)[0].pending_cost == D("1500.00")
