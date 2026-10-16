"""Mesclar contatos pela tela de Contatos (Fase 2.13)."""
from PySide6.QtWidgets import QDialog

from finora.core import db
from finora.services import contacts
from finora.ui import contacts_page


def _id(name: str, eid: int) -> int:
    with db.Session() as s:
        return next(c.id for c in contacts.list_contacts(s, eid) if c.name == name)


def test_mesclar_pelo_cadastro(window, sample, monkeypatch):
    eid = window.profile.id
    with db.Session() as s:
        contacts.create(s, eid, name="ENEL S.A.", person_type="PJ", details={"phone": "1130000000"})
    window.go_to("contacts")
    page = window.page("contacts")
    page.select_contact(_id("Enel", eid))
    form = page.form
    assert form.current.name == "Enel" and not form.merge_btn.isHidden()

    def run(dlg):                                                   # em vez de abrir a janela, escolhe e mescla
        assert dlg.pick.itemText(0) == "ENEL S.A.  ·  provável repetido"    # o duplicado vem primeiro
        dlg.pick.setCurrentIndex(0)
        assert "passam para \"Enel\"" in dlg.info.text()
        dlg.merge()
        return QDialog.Accepted
    monkeypatch.setattr(contacts_page.MergeDialog, "exec", run)
    form.merge_btn.click()
    with db.Session() as s:
        names = [c.name for c in contacts.list_contacts(s, eid)]
        enel = next(c for c in contacts.list_contacts(s, eid) if c.name == "Enel")
    assert "ENEL S.A." not in names and enel.get("phone") == "1130000000"
    assert all(c.name != "ENEL S.A." for c in page._items)          # a lista já atualizou


def test_mesclar_recusa_mostra_o_motivo(window, sample):
    eid = window.profile.id
    with db.Session() as s:
        a = contacts.create(s, eid, name="Fulano", person_type="PF", document="52998224725")
        contacts.create(s, eid, name="Fulano de Tal", person_type="PJ", document="11222333000181")
        keep = next(c for c in contacts.list_contacts(s, eid) if c.id == a)
    dlg = contacts_page.MergeDialog(window, eid, keep, window.page("contacts").t)
    dlg.pick.setCurrentIndex(dlg.pick.findText("Fulano de Tal"))
    dlg.merge()
    assert "diferentes" in dlg.error.text() and not dlg.outcome
