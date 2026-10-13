from datetime import date
from decimal import Decimal as D

from PySide6.QtWidgets import QDialog

from finora.core import db
from finora.services import modules, stock


def _preparar(window):
    with db.Session() as s:
        modules.set_enabled(s, window.profile.id, "sales", True)
        az = stock.create_item(s, window.profile.id, name="Azeite 500 mL", kind="produced", unit="garrafa",
                               sale_price=D("90"))
        stock.move(s, window.profile.id, item_id=az, kind="in", quantity="50", day=date(2026, 9, 1), unit_cost="30")
    window._apply_access()
    return az


def test_pedido_confirmado_baixa_estoque_e_gera_receber(window, monkeypatch):
    from finora.ui.sale_dialog import SaleDialog
    az = _preparar(window)
    assert {"stock", "sales"} <= set(window.visible_keys)
    window.go_to("sales")
    page = window.page("sales")
    assert "Novo pedido" in page.empty.text()

    def novo(dlg):
        dlg.contact.setCurrentText("Empório Bom Gosto")
        assert dlg.p_price.text() == "90,00" and "50 garrafa" in dlg.p_hint.text()
        dlg.p_qty.setText("10")
        dlg.add_line()
        dlg.discount.setText("50")
        dlg.parts.setValue(2)
        assert dlg.total_lbl.text() == "R$ 850,00" and "2x de R$ 425,00" in dlg.parts_lbl.text()
        dlg.save(confirm=True)
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(SaleDialog, "exec", novo)
    page.new_btn.click()
    assert "2 parcelas em Contas a receber" in window.statusBar().currentMessage()
    assert page.rows[0].total == D("850.00") and page.rows[0].status == "confirmed"
    with db.Session() as s:
        assert stock.balance(s, window.profile.id, az) == D("40")
    page.group.button(1).click()                                   # por produto
    assert page.rows[0].name == "Azeite 500 mL" and page.rows[0].cost == D("300.00")
    assert page.rows[0].margin == D("550.00")

    def ver(dlg):
        assert dlg.readonly and dlg.confirm_btn.isHidden() and not dlg.print_btn.isHidden()
        sheet = dlg.order_sheet()
        assert sheet.rows[-1][-1] == D("850.00") and "Empório" in sheet.subtitle
        return QDialog.Rejected

    page.group.button(0).click()
    monkeypatch.setattr(SaleDialog, "exec", ver)
    page.open_sale(0)
