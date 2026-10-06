from datetime import date, timedelta
from decimal import Decimal as D

from PySide6.QtCore import QDate

from finora.core import db
from finora.services import accounts, cards
from finora.ui.card_statements import PayDialog, StatementsDialog
from finora.ui.dashboard_page import ClickRow


def _create_card(window):
    window.go_to("accounts")
    page = window.page("accounts")
    page.name_edit.setText("Itaú")
    page.kind_box.setCurrentIndex(page.kind_box.findData("card"))
    assert page.card_box.isVisible()
    page.closing_spin.setValue(25)
    page.due_spin.setValue(5)
    page.limit_edit.setText("2.000,00")
    page.balance_edit.setText("0")
    page.save_btn.click()
    return page, next(a for a in page._items if a.name == "Itaú")


def _buy(window, desc, amount, when):
    window.new_entry()
    form = window.page("entries").form
    form.account.setCurrentIndex(form.account.findText("Itaú"))
    form.desc.setText(desc)
    form.amount.setText(amount)
    form.due.setDate(QDate(when.year, when.month, when.day))
    return form


def test_criar_cartao_com_fechamento_vencimento_e_limite(window):
    page, card = _create_card(window)
    assert (card.closing_day, card.due_day, card.credit_limit) == (25, 5, D("2000.00"))
    assert card.card_info == "Fecha dia 25 · vence dia 5"
    assert card.id in page._cards                                # mostra fatura atual e limite no cartão
    page._edit(card.id)
    assert page.closing_spin.value() == 25 and page.limit_edit.text() == "2.000,00"


def test_compra_no_cartao_pelo_formulario(window):
    _create_card(window)
    form = _buy(window, "Mercado", "300,00", date.today())
    assert form.due_lbl.label.text() == "Data da compra"
    assert not form.paid_row.isVisible() and form.card_info.isVisible()
    assert "fatura" in form.card_info.text()
    form.save_btn.click()
    with db.Session() as s:
        itau = next(a for a in accounts.list_accounts(s, window.profile.id) if a.name == "Itaú")
        st = cards.current(s, itau.id)
    assert st.charges == D("300.00")
    page = window.page("entries")
    page.year, page.month = st.due.year, st.due.month             # mês do vencimento da fatura
    page.refresh()
    assert page.statements_bar.isVisible() and "Fatura Itaú" in page.statements_bar.text()
    row = next(e for e in page.model.rows if e.description == "Mercado")
    assert row.status_label(date.today()) == "No cartão"


def test_janela_de_faturas_e_pagamento(window, qtbot):
    _create_card(window)
    _buy(window, "Mercado", "300,00", date.today()).save_btn.click()
    with db.Session() as s:
        itau = next(a for a in accounts.list_accounts(s, window.profile.id) if a.name == "Itaú")
    dlg = StatementsDialog(window, itau.id, "BRL", window.page("accounts").t)
    qtbot.addWidget(dlg)
    assert dlg.current.charges == D("300.00") and dlg.table.rowCount() == 1
    assert not dlg.pay_btn.isHidden()                             # botão "Pagar fatura" disponível
    pay = PayDialog(dlg, dlg.current, "BRL", window.profile.id, window.page("accounts").t)
    qtbot.addWidget(pay)
    assert all("Itaú" not in pay.source.itemText(i) for i in range(pay.source.count()))   # cartão não paga cartão
    pay.amount.setText("100,00")
    pay._pay()
    with db.Session() as s:
        st = cards.statement(s, itau.id, dlg.current.due)
    assert (st.paid, st.remaining) == (D("100.00"), D("200.00"))


def test_dashboard_mostra_fatura_que_vence(window):
    _create_card(window)
    # compra feita há ~40 dias: a fatura já fechou e vence em breve (ou já venceu)
    with db.Session() as s:
        itau = next(a for a in accounts.list_accounts(s, window.profile.id) if a.name == "Itaú")
        target = None
        for back in range(20, 70):
            purchase = date.today() - timedelta(days=back)
            _c, due = cards.statement_for(purchase, 25, 5)
            if due <= date.today() + timedelta(days=7):
                target = purchase
                break
    _buy(window, "Farmácia", "80,00", target).save_btn.click()
    window.go_to("dashboard")
    texts = [r.findChildren(type(window.header.title))[1].text() for r in window.page("dashboard").findChildren(ClickRow)]
    assert any(t.startswith("Fatura Itaú") for t in texts)
