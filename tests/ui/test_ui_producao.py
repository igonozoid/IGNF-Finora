from datetime import date
from decimal import Decimal as D

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog, QMessageBox

from finora.core import db
from finora.services import modules, stock


def _preparar(window):
    eid = window.profile.id
    with db.Session() as s:
        modules.set_enabled(s, eid, "production", True)
        azeitona = stock.create_item(s, eid, name="Azeitona", kind="input", unit="kg")
        azeite = stock.create_item(s, eid, name="Azeite 500 mL", kind="produced", unit="garrafa")
        stock.move(s, eid, item_id=azeitona, kind="in", quantity="1000", day=date(2026, 9, 1), unit_cost="4")
    window._apply_access()
    return azeitona, azeite


def _pick(box, item_id):
    box.pick.setCurrentIndex(box.pick.findData(item_id))


def test_lote_concluido_pela_tela(window, monkeypatch):
    from finora.ui.production_dialog import ProductionDialog
    azeitona, azeite = _preparar(window)
    assert {"stock", "production"} <= set(window.visible_keys)
    window.go_to("production")
    page = window.page("production")
    assert "Novo lote" in page.empty.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    def novo(dlg):
        dlg.name.setText("Azeite safra 2026 – lote 1")
        dlg.day.setDate(QDate(2026, 10, 2))
        _pick(dlg.inputs, azeitona)
        assert "1.000 kg" in dlg.inputs.hint.text()
        dlg.inputs.qty.setText("500")
        dlg.inputs.add_line()
        _pick(dlg.outputs, azeite)
        dlg.outputs.qty.setText("100")
        dlg.outputs.add_line()
        dlg.extra.setText("300")
        assert dlg.total_lbl.text() == "R$ 2.300,00"                  # 500 × 4 + 300
        assert dlg.outputs.table.item(0, 3).text() == "R$ 23,00"
        assert dlg.yield_lbl.text() == "20 garrafa por 100 kg"
        dlg.save(finish=True)
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(ProductionDialog, "exec", novo)
    page.new_btn.click()
    assert "Lote 1 concluído" in window.statusBar().currentMessage()
    assert page.rows[0].status == "done" and page.rows[0].total_cost == D("2300.00")
    with db.Session() as s:
        assert stock.balance(s, window.profile.id, azeite) == D("100")
        assert stock.average_cost(s, window.profile.id, azeite) == D("23")

    def ver(dlg):
        assert dlg.readonly and dlg.finish_btn.isHidden() and not dlg.reopen_btn.isHidden()
        sheet = dlg.batch_sheet()
        assert "Azeite safra" in sheet.title and any(r[-1] == D("2300.00") for r in sheet.rows)
        dlg.do_reopen()
        return QDialog.Accepted

    monkeypatch.setattr(ProductionDialog, "exec", ver)
    page.open_batch(0)
    assert page.rows[0].status == "open"
    page.group.button(1).click()
    assert page.rows == []                                             # reaberto: nada produzido


def test_falta_de_insumo_mostra_erro(window, monkeypatch):
    from finora.ui.production_dialog import ProductionDialog
    azeitona, azeite = _preparar(window)
    window.go_to("production")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    def novo(dlg):
        dlg.name.setText("Grande")
        _pick(dlg.inputs, azeitona)
        dlg.inputs.qty.setText("5000")
        dlg.inputs.add_line()
        _pick(dlg.outputs, azeite)
        dlg.outputs.qty.setText("10")
        dlg.outputs.add_line()
        dlg.save(finish=True)
        assert "Falta Azeitona" in dlg.error.text()
        return QDialog.Rejected

    monkeypatch.setattr(ProductionDialog, "exec", novo)
    window.page("production").new_btn.click()
