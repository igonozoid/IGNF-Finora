"""Reclassificar subcategorias na DRE pela tela de Categorias (Fase 2.14)."""
from datetime import date
from decimal import Decimal as D

from PySide6.QtWidgets import QDialog
from sqlalchemy import select

from finora.core import db
from finora.models import Category
from finora.services import accounts, categories, entries, period_lock
from finora.services.entries import EntryData
from finora.ui import reclassify_dialog
from finora.ui.reclassify_dialog import COL_DEST, COL_ON, ReclassifyDialog


def _parent(name: str) -> str:
    with db.Session() as s:
        c = s.scalar(select(Category).where(Category.name == name, Category.parent_id.is_not(None)))
        return s.get(Category, c.parent_id).name if c else ""


def test_reclassificar_com_sugestoes(window, profile, monkeypatch):
    eid = profile.id
    with db.Session() as s:
        mcc = categories.create(s, eid, name="Despesas do MCC", dre_group="outras")
        for name in ("Uber e táxi", "Escola das crianças", "Coisa qualquer"):
            categories.create(s, eid, name=name, parent_id=mcc)
    window.go_to("categories")
    page = window.page("categories")

    def run(dlg):                                                   # em vez de abrir a janela, confere e aplica
        assert dlg.group_box.currentData() == mcc                   # abre direto no grupo do MCC
        names = [r.name for r in dlg.rows]
        assert names == ["Coisa qualquer", "Escola das crianças", "Uber e táxi"]
        assert not dlg.table.cellWidget(0, COL_ON).isChecked()      # sem sugestão: não marcada
        assert dlg.table.cellWidget(2, COL_DEST).currentText().startswith("Transporte")
        assert "2 de 3" in dlg.count.text()
        dlg.table.cellWidget(1, COL_ON).setChecked(False)           # a escola fica para depois
        dlg.apply()
        return QDialog.Accepted
    monkeypatch.setattr(reclassify_dialog.ReclassifyDialog, "exec", run)
    page.reclass_btn.click()
    assert _parent("Uber e táxi") == "Transporte"
    assert _parent("Escola das crianças") == "Despesas do MCC"
    assert _parent("Coisa qualquer") == "Despesas do MCC"


def test_periodo_fechado_mostra_o_motivo_e_nada_muda(window, profile, plus):
    eid = profile.id
    with db.Session() as s:
        mcc = categories.create(s, eid, name="Despesas do MCC", dre_group="outras")
        uber = categories.create(s, eid, name="Uber e taxi", parent_id=mcc)
        bank = accounts.list_accounts(s, eid)[0].id
        entries.create(s, eid, EntryData(kind="expense", description="Corrida", amount=D("30"),
                                         due_date=date(2026, 1, 10), account_id=bank, category_id=uber))
        period_lock.set_lock(s, eid, date(2026, 1, 31))
    page = window.page("categories")
    dlg = ReclassifyDialog(page, eid, page.t)
    assert dlg.table.cellWidget(0, COL_ON).isChecked()
    dlg.apply()
    assert "fechado" in dlg.error.text() and dlg.outcome is None
    assert _parent("Uber e taxi") == "Despesas do MCC"
