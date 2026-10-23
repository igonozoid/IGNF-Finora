"""Aviso de crédito no lançamento a receber e no pedido de venda (Fase 4.5)."""
from datetime import date
from decimal import Decimal as D

from PySide6.QtWidgets import QDialog

from finora.core import db
from finora.services import contacts, modules, stock


def _limite(window, limite="100"):
    with db.Session() as s:
        contacts.create(s, window.profile.id, name="Cliente Caro",
                        credit={"credit_limit": D(limite), "credit_pending": True, "credit_pending_where": "SPC"})


def test_lancamento_a_receber_avisa(plus, window):
    _limite(window)
    window.go_to("entries")
    form = window.page("entries").form
    form.open_new(date.today())
    form._select_kind("income")
    form.amount.setText("250,00")
    form.contact.setCurrentText("Cliente Caro")
    assert form.credit_note.isVisible() or not form.credit_note.isHidden()
    assert "pendência" in form.credit_note.text() and "limite" in form.credit_note.text()
    form._select_kind("expense")
    assert form.credit_note.isHidden()


def test_free_nao_avisa(window):
    _limite(window)
    form = window.page("entries").form
    form.open_new(date.today())
    form._select_kind("income")
    form.contact.setCurrentText("Cliente Caro")
    assert form.credit_note.isHidden()


def test_venda_a_prazo_avisa_e_pergunta(plus, window, monkeypatch, dialogs):
    from finora.ui.sale_dialog import SaleDialog
    _limite(window)
    with db.Session() as s:
        modules.set_enabled(s, window.profile.id, "sales", True)
        az = stock.create_item(s, window.profile.id, name="Azeite", kind="produced", unit="un", sale_price=D("90"))
        stock.move(s, window.profile.id, item_id=az, kind="in", quantity="5", day=date(2026, 9, 1), unit_cost="30")
    window._apply_access()
    window.go_to("sales")
    page = window.page("sales")

    def novo(dlg):
        dlg.contact.setCurrentText("Cliente Caro")
        dlg.p_qty.setText("2")
        dlg.add_line()
        assert "R$ 180,00 agora" in dlg.credit_note.text()
        dialogs.answer_yes = False
        dlg.save(confirm=True)                                     # disse não: continua aberto
        assert dlg.sale_id is None
        dialogs.answer_yes = True
        dlg.save(confirm=True)
        return QDialog.Accepted

    monkeypatch.setattr(SaleDialog, "exec", novo)
    page.new_btn.click()
    assert page.rows[0].status == "confirmed"
