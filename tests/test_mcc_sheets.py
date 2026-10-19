"""Planilhas exportadas do MCC original (Fase 2.10): perfis de coluna e montagem do banco no formato do clone.
As planilhas de teste são inventadas (tools/gerar_mcc_planilhas.py), no formato real descrito na issue #5."""
import sqlite3
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from finora.models import Contact, Entry
from finora.services.mcc_import import conference, mapper, reader, sheets

DATA = Path(__file__).parent / "data" / "mcc_planilhas"


def _all():
    return sorted(DATA.glob("*.csv"))


def test_perfis_e_formato():
    by = {p.name: sheets.read_sheet(p) for p in _all()}
    assert {n: s.kind for n, s in by.items()} == {
        "analitico-despesas.csv": "analitico", "analitico-receitas.csv": "analitico", "contas.csv": "contas",
        "extrato-banco-azul.csv": "extrato", "extrato-caixa.csv": "extrato", "clientes.csv": "cadastro",
        "fornecedores.csv": "cadastro", "centros-fluxo.csv": "centros", "anotacoes.csv": ""}
    desp = by["analitico-despesas.csv"]
    assert len(desp.rows) == 5                                          # rodapé de totais fora
    assert desp.rows[1]["OBSERVACAO"] == "Honorários R$400\nFuncionários R$50"   # quebra de linha juntada
    assert desp.rows[1]["CONTA"] == "Caixa"
    assert len(by["contas.csv"].rows) == 3                              # o bloco repetido não entra
    caixa = by["extrato-caixa.csv"]
    assert (caixa.cash, caixa.opening, caixa.final) == (True, D("0.00"), D("-700.00"))
    azul = by["extrato-banco-azul.csv"]
    assert (azul.account, azul.final) == ("Banco Azul", D("2500.00"))
    assert len(by["clientes.csv"].rows) == 3


def test_monta_o_banco_do_mcc(tmp_path):
    b = sheets.load(_all())
    assert any("anotacoes.csv" in w for w in b.warnings)
    path = sheets.build_db(b, tmp_path / "mcc.db", company="Sítio Exemplo", person_type="PJ", document="11.222.333/0001-81")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    reader.check(con)                                                   # o formato que o importador espera
    pay = {(r["descricao"], r["vencimento"]): r["data_pagamento"] for r in con.execute("SELECT * FROM lancamentos")}
    assert pay[("ENERGIA ELÉTRICA", "2026-01-10")] == "2026-01-10"
    assert pay[("HONORÁRIOS", "2026-01-02")] == "2026-01-02"            # lançado dia 12, pago no dia 2 (extrato)
    assert pay[("HONORÁRIOS", "2026-02-02")] == "2026-02-02"            # mesmo valor: a data mais perto do vencimento
    assert pay[("TARIFA", "2026-01-25")] is None                        # conta sem extrato: fica para o D6
    assert pay[("ADUBO", "2026-03-15")] is None                         # em aberto
    assert (b.paid_dates_found, b.paid_dates_missing) == (4, 1)
    contas = {r["descricao"]: (r["tipo"], r["saldo_inicial"]) for r in con.execute("SELECT * FROM contas")}
    assert contas == {"Banco Azul": ("B", 1000.0), "Caixa": ("C", 0.0), "Banco Verde": ("B", 50.0)}
    (t,) = con.execute("SELECT * FROM movbancarias").fetchall()
    assert (t["tipo"], t["data"], t["valor"], t["observacao"]) == ("T", "2026-01-20", 200.0, "Troco do caixa")
    assert len(b.left_out) == 1 and "05/12/2025" in b.left_out[0]      # um lado só: fora
    assert {(c.account, c.ok) for c in b.balances} == {("Banco Azul", True), ("Caixa", True)}
    people = {r["nome"]: (r["tipo"], r["pessoa"], r["documento"]) for r in con.execute("SELECT * FROM pessoas")}
    assert people == {"MARIA CLIENTE": ("C", "F", "52998224725"), "CONTÁBIL EXEMPLO LTDA": ("F", "J", "11222333000181"),
                      "ENERGIA SUL S.A.": ("F", "F", None)}
    centros = {r["nome"]: (r["aplica_despesa"], r["aplica_receita"]) for r in con.execute("SELECT * FROM centros")}
    assert centros == {"ADMINISTRATIVO": (1, 0), "LAVOURA": (1, 1)}
    assert con.execute("SELECT nome, pessoa, documento FROM empresas").fetchone()[:] == \
        ("Sítio Exemplo", "J", "11222333000181")
    con.close()


def test_saldo_que_nao_bate_vira_aviso(tmp_path):
    b = sheets.load([p for p in _all() if p.name != "contas.csv"])      # sem os saldos iniciais
    sheets.build_db(b, tmp_path / "mcc.db", company="Sítio Exemplo")
    azul = next(c for c in b.balances if c.account == "Banco Azul")
    assert azul.ok                                                      # o saldo anterior do rodapé do extrato supre
    assert any("saldo de contas" in w for w in b.warnings)
    with pytest.raises(ValueError, match="Analítico"):
        sheets.load([DATA / "contas.csv"])


def test_mesmo_caminho_da_importacao(session, plus, tmp_path):
    b = sheets.load(_all())
    path = sheets.build_db(b, tmp_path / "mcc.db", company="Sítio Exemplo")
    with reader.open_copy(path) as con:
        r = mapper.import_companies(session, con)
        rep = conference.build(session, con, r, [date(2026, 1, 31), date(2026, 3, 31)])
    assert rep.ok, rep.problems
    assert len(r.entries) == 7 and len(r.movements) == 1
    honor = session.get(Entry, r.entries[2])
    assert (honor.paid_date, honor.due_date, honor.notes) == (date(2026, 1, 2), date(2026, 1, 2),
                                                              "Honorários R$400\nFuncionários R$50")
    assert session.get(Entry, r.entries[4]).paid_date == date(2026, 1, 25)   # D6: sem extrato, o vencimento
    maria = session.get(Contact, r.contacts[1])
    assert (maria.name, maria.document, maria.is_customer) == ("MARIA CLIENTE", "52998224725", True)
