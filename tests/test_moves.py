"""Aplicação, resgate e saque lançados como receita/despesa viram movimentação (decisão D2)."""
import shutil
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from finora.models import Entry, ImportMap
from finora.services import accounts, categories, moves, period_lock, trash
from finora.services.entries import EntryData, create
from finora.services.mcc_import import conference, mapper, reader

DATA = Path(__file__).parent / "data"


def _setup(s, eid):
    cc = accounts.list_accounts(s, eid)[0].id
    inv = accounts.create(s, eid, name="Sicredinvest", kind="investment", opening_balance=D(0))
    roots = categories.tree(s, eid)
    exp_group = next(r for r in roots if r.kind == "expense")
    inc_group = next(r for r in roots if r.kind == "income")
    cat = {name: categories.create(s, eid, name=name, parent_id=(exp_group if kind == "expense" else inc_group).id)
           for name, kind in (("APLICAÇÃO FINANCEIRA", "expense"), ("Aplicação financeira", "income"),
                              ("SAQUE", "expense"), ("RESGATE APLICAÇÃO", "income"), ("Mercado", "expense"))}
    return cc, inv, cat


def _lanc(s, eid, kind, account, cat, valor, dia, desc):
    return create(s, eid, EntryData(kind=kind, description=desc, amount=D(valor), due_date=dia, account_id=account,
                                    category_id=cat, paid=True, paid_date=dia))[0]


def test_acha_pares_e_avulsos(session, profile):
    s, eid = session, profile.id
    cc, inv, cat = _setup(s, eid)
    a = _lanc(s, eid, "expense", cc, cat["APLICAÇÃO FINANCEIRA"], "1000", date(2026, 7, 15), "Aplicação")
    b = _lanc(s, eid, "income", inv, cat["Aplicação financeira"], "1000", date(2026, 7, 16), "Aplicação")
    c = _lanc(s, eid, "expense", cc, cat["SAQUE"], "200", date(2026, 7, 20), "Saque")      # caixa não lançado
    d = _lanc(s, eid, "income", cc, cat["RESGATE APLICAÇÃO"], "300", date(2026, 8, 1), "Resgate")
    _lanc(s, eid, "expense", cc, cat["Mercado"], "50", date(2026, 7, 20), "Mercado")      # não é movimentação
    found = moves.find(s, eid)
    assert [(m.kind, m.key) for m in found] == [("transfer", (a, b)), ("withdrawal", (c, None)),
                                                ("deposit", (None, d))]
    assert found[0].from_account == "Banco" and found[0].to_account == "Sicredinvest"
    assert moves.find(s, eid, words="mercado")[0].kind == "withdrawal"
    assert moves.find(s, eid, words=" , ") == []
    assert moves.find(s, eid, days=0)[0].kind == "withdrawal"         # 1 dia de diferença: sem par


def test_converter_mantem_saldos_e_tira_da_dre(session, profile):
    s, eid = session, profile.id
    cc, inv, cat = _setup(s, eid)
    a = _lanc(s, eid, "expense", cc, cat["APLICAÇÃO FINANCEIRA"], "1000", date(2026, 7, 15), "Aplicação")
    b = _lanc(s, eid, "income", inv, cat["Aplicação financeira"], "1000", date(2026, 7, 15), "Aplicação")
    c = _lanc(s, eid, "expense", cc, cat["SAQUE"], "200", date(2026, 7, 20), "Saque")
    s.add(ImportMap(source="mcc", kind="lancamentos", source_id="77", target=str(b)))
    s.commit()
    before = {x.id: x.balance for x in accounts.list_accounts(s, eid)}
    done = moves.convert(s, eid, moves.find(s, eid))
    assert done == {"transfer": 1, "withdrawal": 1, "deposit": 0}
    t = s.get(Entry, a)
    assert (t.kind, t.account_id, t.dest_account_id, t.category_id) == ("transfer", cc, inv, None)
    assert trash.get(s, b) is None                                    # a receita sumiu (virou o outro lado)
    assert s.get(Entry, c).kind == "withdrawal"
    assert s.query(ImportMap).filter_by(source_id="77").one().target == str(a)
    assert {x.id: x.balance for x in accounts.list_accounts(s, eid)} == before
    assert moves.find(s, eid) == []                                   # nada mais na DRE como receita/despesa


def test_periodo_fechado_nao_converte(session, profile):
    s, eid = session, profile.id
    cc, _inv, cat = _setup(s, eid)
    _lanc(s, eid, "expense", cc, cat["SAQUE"], "200", date(2026, 7, 20), "Saque")
    period_lock.set_lock(s, eid, date(2026, 7, 31))
    with pytest.raises(ValueError, match="período fechado"):
        moves.convert(s, eid, moves.find(s, eid))


def test_reimportar_o_mcc_nao_desfaz_a_conversao(session, plus, tmp_path):
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    with reader.open_copy(p) as con:
        r = mapper.import_companies(session, con)
    e = next(session.get(Entry, i) for i in r.entries.values()
             if session.get(Entry, i).kind == "expense" and session.get(Entry, i).status == "paid"
             and not period_lock.is_locked(session, session.get(Entry, i).entity_id,
                                           session.get(Entry, i).competence_date))
    moves.convert(session, e.entity_id, [moves.Move(e.paid_date, D(e.amount), "", None, None, e.id, None)])
    with reader.open_copy(p) as con:
        r2 = mapper.import_companies(session, con)
        rep = conference.build(session, con, r2)
    assert session.get(Entry, e.id).kind == "withdrawal"
    assert len(r2.converted) == 1 and rep.ok, rep.problems
    assert any("transferência, depósito ou retirada" in n for n in rep.notes)
