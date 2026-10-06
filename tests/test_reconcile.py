from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from finora.services import accounts, categories, entries, reconcile
from finora.services.entries import EntryData

OFX = (Path(__file__).parent / "data" / "extrato.ofx").read_bytes()


def _setup(s, eid):
    bank = accounts.list_accounts(s, eid)[0].id
    luz = dict((label, cid) for cid, label in categories.choices(s, eid, "expense"))["Moradia › Luz"]
    # salário já registrado como recebido; luz em aberto, vencendo um dia antes do débito
    entries.create(s, eid, EntryData(kind="income", description="Salário", amount=D("5000"),
                                     due_date=date(2026, 10, 2), account_id=bank, paid=True,
                                     paid_date=date(2026, 10, 2)))
    (luz_id,) = entries.create(s, eid, EntryData(kind="expense", description="Conta de luz", amount=D("180.40"),
                                                 due_date=date(2026, 10, 2), account_id=bank, category_id=luz))
    return bank, luz, luz_id


def test_importa_sem_duplicar_e_liga_o_que_ja_estava_pago(session, profile):
    s, eid = session, profile.id
    bank, _luz, _ = _setup(s, eid)
    r = reconcile.import_ofx(s, eid, bank, OFX)
    assert (r.new, r.repeated, r.auto_matched) == (4, 0, 1)            # salário ligado sozinho
    assert (r.first, r.last) == (date(2026, 10, 1), date(2026, 10, 5))
    again = reconcile.import_ofx(s, eid, bank, OFX)
    assert (again.new, again.repeated) == (0, 4)
    assert reconcile.counts(s, eid, bank) == {"pending": 3, "matched": 1, "ignored": 0}


def test_sugere_conta_em_aberto_e_confirma(session, profile):
    s, eid = session, profile.id
    bank, _luz, luz_id = _setup(s, eid)
    reconcile.import_ofx(s, eid, bank, OFX)
    pend = {ln.memo: ln for ln in reconcile.lines(s, eid, bank)}
    enel = pend["PAG BOLETO ENEL"]
    assert enel.suggestion.kind == "entry" and enel.suggestion.entry_id == luz_id
    assert pend["DEB AUT SOFTPDV"].suggestion.kind == "new"
    reconcile.confirm(s, enel.id, luz_id)
    e = entries.get(s, luz_id)
    assert e.status == "paid" and e.paid_date == date(2026, 10, 3)        # pago na data do extrato
    with pytest.raises(ValueError, match="já está ligado"):
        reconcile.confirm(s, pend["DEB AUT SOFTPDV"].id, luz_id)


def test_cria_lancamento_e_aprende_a_categoria(session, profile):
    s, eid = session, profile.id
    bank, luz, _ = _setup(s, eid)
    reconcile.import_ofx(s, eid, bank, OFX)
    tarifa = next(ln for ln in reconcile.lines(s, eid, bank) if ln.memo.startswith("TAR PACOTE"))
    new_id = reconcile.create(s, tarifa.id, "Tarifa do banco", luz)
    e = entries.get(s, new_id)
    assert (e.kind, e.amount, e.status, e.paid_date) == ("expense", D("39.90"), "paid", date(2026, 10, 4))
    # no mês seguinte, a mesma tarifa (com outra data no texto) já vem com a descrição e a categoria
    nov = OFX.replace(b"A003", b"B003").replace(b"20261004", b"20261104").replace(b"10/2026", b"11/2026")
    reconcile.import_ofx(s, eid, bank, nov)
    again = next(ln for ln in reconcile.lines(s, eid, bank) if ln.posted == date(2026, 11, 4))
    assert again.suggestion.kind == "new" and again.suggestion.description == "Tarifa do banco"
    assert again.suggestion.category_id == luz


def test_ignorar_desfazer_e_lancamento_excluido(session, profile):
    s, eid = session, profile.id
    bank, _luz, luz_id = _setup(s, eid)
    reconcile.import_ofx(s, eid, bank, OFX)
    pend = {ln.memo: ln for ln in reconcile.lines(s, eid, bank)}
    reconcile.ignore(s, pend["DEB AUT SOFTPDV"].id)
    reconcile.confirm(s, pend["PAG BOLETO ENEL"].id, luz_id)
    assert reconcile.counts(s, eid, bank) == {"pending": 1, "matched": 2, "ignored": 1}
    reconcile.undo(s, pend["DEB AUT SOFTPDV"].id)
    entries.delete(s, luz_id)                       # excluiu o lançamento: a linha volta a pendente
    memos = {ln.memo for ln in reconcile.lines(s, eid, bank)}
    assert {"DEB AUT SOFTPDV", "PAG BOLETO ENEL"} <= memos


def test_arquivo_invalido(session, profile):
    bank = accounts.list_accounts(session, profile.id)[0].id
    with pytest.raises(ValueError, match="OFX"):
        reconcile.import_ofx(session, profile.id, bank, b"isso nao e um extrato")
