"""Relatório de conferência da importação do MCC (Fase 2.7)."""
import json
import shutil
import sqlite3
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from finora.models import Entry
from finora.services.mcc_import import conference, mapper, reader

DATA = Path(__file__).parent / "data"
GABARITO = json.loads((DATA / "mcc_exemplo_gabarito.json").read_text(encoding="utf-8"))
DAYS = [date.fromisoformat(d) for d in GABARITO["saldos"]]


def _import(session, path):
    con_ctx = reader.open_copy(path)
    con = con_ctx.__enter__()
    r = mapper.import_companies(session, con)
    return con_ctx, con, r


@pytest.fixture
def mcc(tmp_path):
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    return p


def test_exemplo_bate_e_o_d6_fica_explicado(session, plus, mcc):
    ctx, con, r = _import(session, mcc)
    try:
        rep = conference.build(session, con, r, DAYS)
    finally:
        ctx.__exit__(None, None, None)
    assert rep.ok and rep.problems == []
    by = {(b.mcc_account, b.day): b for b in rep.balances}
    for day, contas in GABARITO["saldos"].items():                          # o lado do MCC é o do gabarito
        for conta, g in contas.items():
            b = by[(int(conta), date.fromisoformat(day))]
            assert (b.mcc_real, b.mcc_forecast) == (D(str(g["realizado"])), D(str(g["previsto"])))
    caixa = by[(2, date(2026, 6, 30))]                                      # D6: R$ 120 pago sem data, em 02/04
    assert caixa.finora_real == caixa.mcc_real - 120 and caixa.explained_real == D("-120.00")
    assert len(rep.totals) == 2 * 5 and all(t.ok for t in rep.totals)
    assert any("sem data de pagamento" in n for n in rep.notes) and any("A revisar" in n for n in rep.notes)
    sheet = conference.to_sheet(rep)
    assert sheet.subtitle == "Bateu" and len(sheet.rows) == len(rep.balances) + len(rep.totals)


def test_arredondamento_tambem_fica_explicado(session, plus, mcc):
    con = sqlite3.connect(mcc)
    con.execute("UPDATE lancamentos SET valor=1333.335 WHERE id=12")        # parcela em aberto: só o previsto
    con.execute("UPDATE lancamentos SET valor=412.374 WHERE id=1")          # paga
    con.execute("UPDATE contas SET saldo_inicial=10000.004 WHERE id=1")
    con.commit()
    con.close()
    ctx, c, r = _import(session, mcc)
    try:
        rep = conference.build(session, c, r, DAYS)
    finally:
        ctx.__exit__(None, None, None)
    assert len(r.rounding) == 3 and rep.ok, rep.problems
    b = next(x for x in rep.balances if x.mcc_account == 1 and x.day == date(2026, 9, 30))
    assert b.explained_real != b.explained_forecast                         # a parcela em aberto só muda o previsto


def test_diferenca_sem_explicacao_nao_deixa_concluir(session, plus, mcc):
    ctx, con, r = _import(session, mcc)
    try:
        session.get(Entry, r.entries[18]).amount = D("9000.00")            # alguém mexeu depois de importar
        session.commit()                                                    # (junho: fora do período fechado)
        rep = conference.build(session, con, r, DAYS)
    finally:
        ctx.__exit__(None, None, None)
    assert not rep.ok
    assert any("BANCO DO BRASIL" in p and "sem explicação" in p for p in rep.problems)
    assert any("Recebido" in p for p in rep.problems)
    assert conference.to_sheet(rep).subtitle.endswith("diferença(s) sem explicação")


def test_datas_padrao(mcc):
    with reader.open_copy(mcc) as con:
        days = conference.default_days(con, today=date(2026, 10, 16))
    assert days == [date(2026, 9, 30), date(2026, 10, 16), date(2026, 11, 30)]
