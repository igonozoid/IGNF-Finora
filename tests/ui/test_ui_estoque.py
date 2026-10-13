from decimal import Decimal as D

from PySide6.QtWidgets import QDialog

from finora.core import db
from finora.services import modules, stock


def _ligar(window):
    window.go_to("settings")
    window.page("settings").module_checks["stock"].setChecked(True)


def test_estoque_aparece_so_com_o_modulo_ligado(window):
    assert "stock" not in window.visible_keys
    _ligar(window)
    assert "stock" in window.visible_keys
    with db.Session() as s:
        assert modules.is_on(s, window.profile.id, "stock")
    window.page("settings").module_checks["stock"].setChecked(False)
    assert "stock" not in window.visible_keys


def test_cadastrar_item_entrada_com_conta_a_pagar_e_saida(window, monkeypatch):
    from finora.ui.stock_dialogs import MoveDialog
    _ligar(window)
    window.go_to("stock")
    page = window.page("stock")
    assert not page.table.isVisible() and "Novo item" in page.empty.text()
    page.new_item()
    page.f_name.setText("Garrafa 500 mL")
    page.f_kind.setCurrentIndex(page.f_kind.findData("input"))
    page.f_min.setText("100")
    page.save_item()
    assert [i.name for i in page.items] == ["Garrafa 500 mL"] and page.current.name == "Garrafa 500 mL"

    def entrada(dlg):
        dlg.qty.setText("200")
        dlg.cost.setText("2,00")
        dlg.contact.setCurrentText("Vidraria Sul")
        assert "Total: R$ 400,00" in dlg.total_lbl.text() and dlg.payable.isChecked()
        dlg.save()
        assert dlg.error.isHidden()
        return QDialog.Accepted

    monkeypatch.setattr(MoveDialog, "exec", entrada)
    page.in_btn.click()
    assert page.current.balance == D("200") and "Contas a pagar" in window.statusBar().currentMessage()

    def saida(dlg):
        dlg.qty.setText("150")
        dlg.save()
        return QDialog.Accepted

    monkeypatch.setattr(MoveDialog, "exec", saida)
    page.out_btn.click()
    assert page.current.balance == D("50") and page.current.below_min
    assert page.hist.rowCount() == 2 and page.export_sheet().rows[0][1] == "Garrafa 500 mL"
    with db.Session() as s:
        assert stock.low_stock(s, window.profile.id)[0].name == "Garrafa 500 mL"
