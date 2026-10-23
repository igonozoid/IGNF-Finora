"""Anexos e foto do contato (Fase 4.3)."""
import pytest

from finora.services import attachments, contacts


def test_anexar_ao_contato(session, profile, tmp_path):
    s = session
    cid = contacts.create(s, profile.id, name="Maria")
    f = tmp_path / "contrato.pdf"
    f.write_bytes(b"%PDF-1.4 teste")
    aid = attachments.add_to_contact(s, cid, f)
    assert [a.filename for a in attachments.list_for_contact(s, cid)] == ["contrato.pdf"]
    assert attachments.content(s, aid) == ("contrato.pdf", b"%PDF-1.4 teste")
    with pytest.raises(ValueError, match="Salve o contato"):
        attachments.add_to_contact(s, 9999, f)


def test_foto_mesclar_e_excluir(session, profile, tmp_path):
    s, eid = session, profile.id
    keep = contacts.create(s, eid, name="Enel")
    drop = contacts.create(s, eid, name="ENEL SA")
    contacts.set_photo(s, drop, b"png")
    f = tmp_path / "ficha.txt"
    f.write_text("x")
    attachments.add_to_contact(s, drop, f)
    contacts.merge(s, keep, drop)
    assert contacts.get_photo(s, keep) == b"png"
    assert len(attachments.list_for_contact(s, keep)) == 1
    contacts.set_photo(s, keep, None)
    assert contacts.get_photo(s, keep) is None
    contacts.delete(s, keep)
    assert attachments.list_for_contact(s, keep) == []
    with pytest.raises(ValueError, match="grande"):
        contacts.set_photo(s, contacts.create(s, eid, name="X"), b"0" * (contacts.PHOTO_MAX + 1))
