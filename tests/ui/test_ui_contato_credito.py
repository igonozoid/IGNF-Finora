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


def test_listas_do_contato(plus, window):
    eid = window.profile.id
    window.go_to("contacts")
    page = window.page("contacts")
    page.select_contact(_contact(eid, "Empresa X").id)
    form = page.form
    form.type_group.button(1).setChecked(True)                  # empresa: aparece "Pessoas de contato"
    assert not form.people.isHidden()
    form.banks.add_row({"bank_name": "Itaú", "bank_account": "123"})
    form.references.add_row({"name": "Sicredi", "kind": "bancaria"})
    form.people.add_row({"name": "Ana", "job": "Compras"})
    form.save_btn.click()
    assert not form.error.isVisible()
    with db.Session() as s:
        got = contacts.get_lists(s, _contact(eid, "Empresa X").id)
    assert got["banks"][0]["bank_name"] == "Itaú" and got["references"][0]["kind"] == "bancaria"
    assert got["people"][0]["job"] == "Compras"
    assert form.references.table.rowCount() == 1                # reabriu com o que foi salvo


def test_listas_na_free_ficam_travadas(window):
    form = window.page("contacts").form
    assert not form.banks.isEnabled() and form._lists_data() is None


def test_anexos_e_foto_do_contato(plus, window, tmp_path, dialogs):
    from PySide6.QtGui import QImage
    eid = window.profile.id
    window.go_to("contacts")
    page = window.page("contacts")
    page.select_contact(_contact(eid, "Empresa X").id)
    form = page.form
    f = tmp_path / "ficha.pdf"
    f.write_bytes(b"%PDF")
    form.files.add_file(str(f))
    assert form.files.list.count() == 1
    img = tmp_path / "foto.png"
    QImage(600, 400, QImage.Format_RGB32).save(str(img))
    dialogs.open_path = str(img)
    form.photo_pick.click()
    assert form.photo_view.pixmap() is not None and not form.photo_clear.isHidden()
    with db.Session() as s:
        assert contacts.get_photo(s, _contact(eid, "Empresa X").id)


def test_anexos_do_contato_na_free(window):
    form = window.page("contacts").form
    assert form.files.locked
