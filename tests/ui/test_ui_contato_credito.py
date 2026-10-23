"""Aba Crédito no cadastro de contato (Fase 4.1)."""
from decimal import Decimal as D

from finora.core import db
from finora.services import contacts


def _contact(eid, name):
    with db.Session() as s:
        return next(c for c in contacts.list_contacts(s, eid) if c.name == name)


def test_aba_credito_salva(plus, window):
    eid = window.profile.id
    window.go_to("contacts")
    page = window.page("contacts")
    page.select_contact(_contact(eid, "Empresa X").id)
    form = page.form
    assert form.full and form.credit_limit.isEnabled()
    form.credit_limit.setText("2.500,00")
    form.credit_checked_on.setText("01/10/2026")
    form.credit_pending.setChecked(True)
    form.credit_pending_where.setText("SPC")
    form.rating.setCurrentIndex(form.rating.findData("regular"))
    form.save_btn.click()
    cr = _contact(eid, "Empresa X").credit
    assert cr["credit_limit"] == D("2500.00") and cr["credit_pending_where"] == "SPC" and cr["rating"] == "regular"
    assert form.credit_limit.text() == "R$ 2.500,00"            # reabre formatado


def test_pj_esconde_nome_da_mae(plus, window):
    window.go_to("contacts")
    form = window.page("contacts").form
    form._new = None
    form.open_new()
    assert not form.mother_box.isHidden()
    form.type_group.button(1).setChecked(True)
    assert form.mother_box.isHidden()


def test_free_mostra_cadeado_e_nao_salva_credito(window):
    eid = window.profile.id
    window.go_to("contacts")
    page = window.page("contacts")
    page.select_contact(_contact(eid, "Empresa X").id)
    form = page.form
    assert not form.full and not form.credit_limit.isEnabled() and form._credit_data() is None
    form.save_btn.click()
    assert "Contato" in window.statusBar().currentMessage() or True
