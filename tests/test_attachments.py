from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, attachments, entries
from finora.services.entries import EntryData


def _entry(s, eid):
    bank = accounts.list_accounts(s, eid)[0].id
    return entries.create(s, eid, EntryData(kind="expense", description="Luz", amount=D("100"),
                                            due_date=date(2026, 10, 5), account_id=bank))[0]


def test_anexar_listar_baixar_e_remover(session, profile, tmp_path):
    s = session
    entry = _entry(s, profile.id)
    pdf = tmp_path / "boleto.pdf"
    pdf.write_bytes(b"%PDF-1.4 conteudo")
    a = attachments.add(s, entry, pdf, today=date(2026, 10, 6))
    (view,) = attachments.list_for(s, entry)
    assert (view.filename, view.size, view.added, view.size_label) == ("boleto.pdf", 17, date(2026, 10, 6), "0 KB")
    assert attachments.counts(s, [entry, 999]) == {entry: 1}
    out = attachments.save_copy(s, a, tmp_path / "copia" / "x.pdf")
    assert out.read_bytes() == b"%PDF-1.4 conteudo"
    attachments.remove(s, a)
    assert attachments.list_for(s, entry) == []


def test_validacoes(session, profile, tmp_path):
    s = session
    entry = _entry(s, profile.id)
    exe = tmp_path / "virus.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(ValueError, match="tipo de arquivo"):
        attachments.add(s, entry, exe)
    empty = tmp_path / "vazio.png"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="vazio"):
        attachments.add(s, entry, empty)
    big = tmp_path / "grande.jpg"
    big.write_bytes(b"0" * (attachments.MAX_SIZE + 1))
    with pytest.raises(ValueError, match="10 MB"):
        attachments.add(s, entry, big)
    with pytest.raises(ValueError, match="abrir"):
        attachments.add(s, entry, tmp_path / "nao-existe.pdf")


def test_lixeira_guarda_os_anexos(session, profile, tmp_path):
    from finora.services import trash
    s = session
    entry = _entry(s, profile.id)
    f = tmp_path / "nota.png"
    f.write_bytes(b"png")
    attachments.add(s, entry, f)
    entries.delete(s, entry)
    trash.restore(s, [entry])
    assert attachments.counts(s, [entry]) == {entry: 1}
