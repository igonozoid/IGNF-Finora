"""Converter aplicação/resgate/saque lançados como receita e despesa (decisão D2)."""
from datetime import date
from decimal import Decimal as D

from PySide6.QtWidgets import QDialog

from finora.core import db
from finora.models import Entry
from finora.services import accounts, categories
from finora.services.entries import EntryData, create
from finora.ui import moves_dialog


def _dados(eid):
    with db.Session() as s:
        cc = accounts.list_accounts(s, eid)[0].id
        inv = accounts.create(s, eid, name="Aplicação", kind="investment", opening_balance=D(0))
        roots = categories.tree(s, eid)
        exp = categories.create(s, eid, name="APLICAÇÃO", parent_id=next(r for r in roots if r.kind == "expense").id)
        inc = categories.create(s, eid, name="Aplicação", parent_id=next(r for r in roots if r.kind == "income").id)
        sq = categories.create(s, eid, name="SAQUE", parent_id=next(r for r in roots if r.kind == "expense").id)
        day = date(2026, 7, 15)
        a = create(s, eid, EntryData(kind="expense", description="Aplicação", amount=D("500"), due_date=day,
                                     account_id=cc, category_id=exp, paid=True, paid_date=day))[0]
        create(s, eid, EntryData(kind="income", description="Aplicação", amount=D("500"), due_date=day,
                                 account_id=inv, category_id=inc, paid=True, paid_date=day))
        b = create(s, eid, EntryData(kind="expense", description="Saque", amount=D("50"), due_date=day,
                                     account_id=cc, category_id=sq, paid=True, paid_date=day))[0]
    return a, b


def test_converter_pela_tela(plus, window, monkeypatch):
    a, b = _dados(window.profile.id)
    window.go_to("settings")
    page = window.page("settings")

    def run(dlg):
        assert [m.kind for m in dlg.rows] == ["transfer", "withdrawal"]
        assert dlg.table.cellWidget(0, 0).isChecked() and not dlg.table.cellWidget(1, 0).isChecked()
        assert dlg.count.text() == "1 de 2 marcada(s)"
        dlg.apply()
        return QDialog.Accepted

    monkeypatch.setattr(moves_dialog.MovesDialog, "exec", run)
    page.moves_btn.click()
    assert "1 transferência(s)" in window.statusBar().currentMessage()
    with db.Session() as s:
        assert s.get(Entry, a).kind == "transfer" and s.get(Entry, b).kind == "expense"


def test_palavras_vazias_nao_acham_nada(plus, window):
    _dados(window.profile.id)
    window.go_to("settings")
    dlg = moves_dialog.MovesDialog(window, window.profile.id, "BRL", window.page("settings").t)
    dlg.words.setText("")
    dlg.load()
    assert dlg.rows == [] and not dlg.apply_btn.isEnabled() and "Nada encontrado" in dlg.count.text()
