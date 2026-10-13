from datetime import date
from decimal import Decimal as D

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog

from finora.core import db
from finora.services import accounts, entries, livestock, modules, rural, stock


def _preparar(window):
    eid = window.profile.id
    with db.Session() as s:
        modules.set_enabled(s, eid, "livestock", True)
        farm = rural.save_farm(s, eid, name="El Rocio II")
        p1 = rural.save_area(s, eid, farm_id=farm, name="Piquete 1", kind="pasture")
        p2 = rural.save_area(s, eid, farm_id=farm, name="Piquete 2", kind="pasture")
        vacina = stock.create_item(s, eid, name="Vacina aftosa", kind="input", unit="dose")
        stock.move(s, eid, item_id=vacina, kind="in", quantity="100", day=date(2026, 1, 2), unit_cost="2.5")
    window._apply_access()
    return p1, p2, vacina


def test_lote_compra_com_conta_vacina_e_troca_de_piquete(window, monkeypatch):
    from finora.ui.livestock_dialogs import EventDialog, LotDialog
    p1, p2, vacina = _preparar(window)
    assert {"stock", "rural", "livestock"} <= set(window.visible_keys)
    window.go_to("livestock")
    page = window.page("livestock")
    assert "Novo lote" in page.empty.text()

    def lote(dlg):
        dlg.name.setText("Vacas de cria")
        dlg.category.setCurrentText("Vaca")
        dlg.area.setCurrentIndex(dlg.area.findData(p1))
        dlg._ok()
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(LotDialog, "exec", lote)
    page.open_lot(None)
    assert page.rows[0].name == "Vacas de cria" and page.rows[0].area == "El Rocio II › Piquete 1"

    def compra(dlg):
        dlg.day.setDate(QDate(2026, 1, 10))
        dlg.kind.setCurrentIndex(dlg.kind.findData("purchase"))
        assert not dlg.fin_box.isHidden() and dlg.inputs.isHidden()
        assert "Contas a pagar" in dlg.fin.text()
        dlg.heads.setValue(30)
        dlg.weight.setText("400")
        dlg.value.setText("90.000,00")
        dlg.contact.setCurrentText("Leilão Pampa")
        dlg.save()
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(EventDialog, "exec", compra)
    page.new_btn.click()
    assert page.rows[0].heads == 30 and page.rows[0].weight is None          # peso do lote vem das pesagens

    def vacinar(dlg):
        dlg.day.setDate(QDate(2026, 2, 1))
        dlg.kind.setCurrentIndex(dlg.kind.findData("health"))
        assert dlg.fin_box.isHidden() and not dlg.inputs.isHidden() and dlg.fields["heads"][1].isHidden()
        dlg.inputs.pick.setCurrentIndex(dlg.inputs.pick.findData(vacina))
        dlg.inputs.qty.setText("30")
        dlg.inputs.add_line()
        dlg.other.setText("150")
        assert "225,00" in dlg.cost_lbl.text()                            # 30 × 2,50 + 150
        dlg.desc.setText("Aftosa")
        dlg.save()
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(EventDialog, "exec", vacinar)
    page.new_btn.click()

    def piquete(dlg):
        dlg.day.setDate(QDate(2026, 3, 1))
        dlg.kind.setCurrentIndex(dlg.kind.findData("move"))
        dlg.area.setCurrentIndex(dlg.area.findData(p2))
        dlg.save()
        assert dlg.error.isHidden(), dlg.error.text()
        return QDialog.Accepted

    monkeypatch.setattr(EventDialog, "exec", piquete)
    page.new_btn.click()
    assert page.rows[0].area == "El Rocio II › Piquete 2"
    with db.Session() as s:
        eid = window.profile.id
        assert stock.balance(s, eid, vacina) == D("70")
        conta = [e for e in entries.list_entries(s, eid, year=2026, month=1, period="all")
                 if e.description.startswith("Compra de animais")][0]
        assert conta.amount == D("90000.00") and conta.contact == "Leilão Pampa"
    page._open_row(0)                                                   # dois cliques: registros do lote
    assert page.view == "events" and len(page.rows) == 3
    assert page.rows[0].kind == "move" and "Piquete 2" in page.rows[0].detail

    def ver(dlg):
        assert dlg.kind.currentData() == "health" and len(dlg.inputs.lines) == 1
        assert dlg.desc.text() == "Aftosa" and not dlg.delete_btn.isHidden()
        return QDialog.Rejected

    monkeypatch.setattr(EventDialog, "exec", ver)
    page.open_event(1)
    page.group.button(2).click()
    page.period.setCurrentIndex(page.period.findData("all"))
    row = page.rows[0]
    assert (row.bought, row.purchases, row.cost, row.per_head) == (30, D("90000.00"), D("225.00"), D("7.50"))
