"""Planilhas exportadas do MCC original (Fase 2.10): perfis de coluna e montagem do banco no formato do clone.
As planilhas de teste são inventadas (tools/gerar_mcc_planilhas.py), no formato real descrito na issue #5."""
import sqlite3
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import func, select

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
        "fornecedores.csv": "cadastro", "centros-fluxo.csv": "centros", "centros-receitas.csv": "centros",
        "anotacoes.csv": ""}
    desp = by["analitico-despesas.csv"]
    assert len(desp.rows) == 11                                         # rodapé de totais fora
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


def _centers(path):
    con = sqlite3.connect(path)
    out = {(d, v): c for d, v, c in con.execute(
        "SELECT l.descricao, l.vencimento, c.nome FROM lancamentos l LEFT JOIN centros c ON c.id = l.centro_id")}
    con.close()
    return out


def test_centro_em_branco_vem_do_relatorio_por_centro(tmp_path):
    b = sheets.load(_all())
    cc = _centers(sheets.build_db(b, tmp_path / "mcc.db", company="Sítio Exemplo"))
    assert cc[("VENDA DE MEL", "2026-03-30")] == "LAVOURA"             # em branco no analítico
    assert cc[("TARIFA", "2026-01-25")] is None                         # despesa: sem o relatório de despesas
    assert b.centers_filled == 1
    assert not any("sem centro" in w for w in b.warnings)
    b = sheets.load([p for p in _all() if p.name != "centros-receitas.csv"])
    cc = _centers(sheets.build_db(b, tmp_path / "sem.db", company="Sítio Exemplo"))
    assert cc[("VENDA DE MEL", "2026-03-30")] is None and b.centers_filled == 0


def test_centro_que_nao_fecha_fica_em_branco(tmp_path):
    (tmp_path / "centros-receitas.csv").write_bytes("\r\n".join([
        "Relatório de Receitas por Centro de Custo;", "Período de 01/01/2000 a 31/12/2030;", " ;",
        "CENTRO DE CUSTO;DESCRIÇÃO DO MOVIMENTO;TOTAL;",
        "LAVOURA;VENDA DE MEL;R$ 2.400,00;",                             # falta 400, não os 500 sem centro
        ""]).encode("cp1252"))
    b = sheets.load([p for p in _all() if p.name != "centros-receitas.csv"] + [tmp_path / "centros-receitas.csv"])
    cc = _centers(sheets.build_db(b, tmp_path / "mcc.db", company="Sítio Exemplo"))
    assert cc[("VENDA DE MEL", "2026-03-30")] is None and b.centers_filled == 0
    assert any("1 lançamento(s) sem centro" in w for w in b.warnings)


def test_saldo_que_nao_bate_vira_aviso(tmp_path):
    b = sheets.load([p for p in _all() if p.name != "contas.csv"])      # sem os saldos iniciais
    sheets.build_db(b, tmp_path / "mcc.db", company="Sítio Exemplo")
    azul = next(c for c in b.balances if c.account == "Banco Azul")
    assert azul.ok                                                      # o saldo anterior do rodapé do extrato supre
    assert any("saldo de contas" in w for w in b.warnings)
    with pytest.raises(ValueError, match="Analítico"):
        sheets.load([DATA / "contas.csv"])


def _entry(s, description, due):
    return s.scalar(select(Entry).where(Entry.description == description, Entry.due_date == due))


def _import(session, tmp_path, files, name="mcc.db"):
    b = sheets.load(files)
    path = sheets.build_db(b, tmp_path / name, company="Sítio Exemplo")
    with reader.open_copy(path) as con:
        r = mapper.import_companies(session, con)
        rep = conference.build(session, con, r, [date(2026, 1, 31), date(2026, 3, 31)])
    return r, rep


def test_mesmo_caminho_da_importacao(session, plus, tmp_path):
    r, rep = _import(session, tmp_path, _all())
    assert rep.ok, rep.problems
    assert len(r.entries) == 13 and len(r.movements) == 1
    assert list(r.entities) == [sheets.company_id("Sítio Exemplo")]
    honor = _entry(session, "HONORÁRIOS", date(2026, 1, 2))
    assert (honor.paid_date, honor.notes) == (date(2026, 1, 2), "Honorários R$400\nFuncionários R$50")
    assert _entry(session, "TARIFA", date(2026, 1, 25)).paid_date == date(2026, 1, 25)   # D6: sem extrato
    maria = session.scalar(select(Contact).where(Contact.name == "MARIA CLIENTE"))
    assert (maria.document, maria.is_customer) == ("52998224725", True)


def test_reimportar_planilhas_atualiza_sem_duplicar(session, plus, tmp_path):
    r1, _ = _import(session, tmp_path, _all())
    r2, _ = _import(session, tmp_path, list(reversed(_all())), "de-novo.db")   # outra ordem: mesmos ids
    assert r2.reimport and (r2.created, r2.updated, r2.trashed) == (0, 0, 0)
    assert r2.entries == r1.entries

    newer = tmp_path / "nova"                                            # exportação mais nova: o adubo foi pago
    newer.mkdir()
    for f in _all():
        text = f.read_bytes().decode("cp1252")
        if f.name == "analitico-despesas.csv":
            text = text.replace("R$ 1.000,00;P;15/03/2026", "R$ 1.000,00;V;15/03/2026")
        if f.name == "extrato-banco-azul.csv":
            text = text.replace(";;;;;R$ 2.000,00;R$ 500,00;",
                                "15/03/2026;PAGTO.: ADUBO;Agro Insumos;Desc;;;R$ 1.000,00;\r\n;;;;;R$ 2.000,00;R$ 1.500,00;")
            text = text.replace("R$ 2.500,00;", "R$ 1.500,00;")
        (newer / f.name).write_bytes(text.encode("cp1252"))
    r3, rep = _import(session, tmp_path, sorted(newer.glob("*.csv")), "nova.db")
    assert (r3.created, r3.updated, r3.trashed) == (0, 1, 0) and rep.ok, rep.problems
    adubo = _entry(session, "ADUBO", date(2026, 3, 15))
    assert (adubo.status, adubo.paid_date) == ("paid", date(2026, 3, 15))
    assert session.scalar(select(func.count(Entry.id)).where(Entry.description == "ADUBO")) == 1


def test_parcelas_reagrupadas(session, plus, tmp_path):
    b = sheets.load(_all())
    path = sheets.build_db(b, tmp_path / "mcc.db", company="Sítio Exemplo")
    con = sqlite3.connect(path)
    rows = {(d, v): (g, p, t) for d, v, g, p, t in con.execute(
        "SELECT descricao, vencimento, grupo, parcela, total_parcelas FROM lancamentos")}
    con.close()
    seguro = [rows[("SEGURO", f"2026-0{m}-10")] for m in (2, 3, 4)]
    assert len({g for g, _p, _t in seguro}) == 1 and [(p, t) for _g, p, t in seguro] == [(1, 3), (2, 3), (3, 3)]
    nf = [rows[("CONSERTO", d)] for d in ("2026-02-20", "2026-03-20")]
    assert nf[0][0] == nf[1][0] and [(p, t) for _g, p, t in nf] == [(1, 2), (2, 2)]
    assert rows[("HONORÁRIOS", "2026-03-02")] == (None, None, None)       # "Ref 02/26" é mês/ano
    assert rows[("ADUBO", "2026-03-15")] == (None, None, None)
    assert b.series == 2

    r, rep = _import(session, tmp_path, _all(), "de-novo.db")
    assert rep.ok, rep.problems
    seg = list(session.scalars(select(Entry).where(Entry.description == "SEGURO").order_by(Entry.due_date)))
    assert len({e.series_id for e in seg}) == 1 and seg[0].series_id
    assert [e.installment for e in seg] == ["1/3", "2/3", "3/3"]


def test_marcador_de_parcela():
    m = sheets._marker
    assert m({"OBSERVACAO": "Empréstimo  Parcela: 2/24"}) == ("OBSERVACAO", 2, 24)
    assert m({"OBSERVACAO": "Parcela Financiamento 23_60"}) == ("OBSERVACAO", 23, 60)
    assert m({"DOCUMENTO": "NF-4521 1/3"}) == ("DOCUMENTO", 1, 3)
    assert m({"OBSERVACAO": "Ref. 07/24"}) is None                     # mês/ano
    assert m({"OBSERVACAO": "Referente a 04/23 05/23 e 06/23"}) is None
    assert m({"OBSERVACAO": "Vence em 20/08/2026"}) is None              # data
    assert m({"OBSERVACAO": "3/2"}) is None


def test_mesma_pessoa_em_dois_cadastros_vira_um_contato_completo(session, plus, tmp_path):
    """No MCC a mesma pessoa aparece como cliente (só o nome) e fornecedor (completo), e às vezes com o nome escrito
    de outro jeito mas o mesmo CNPJ: um contato só, com os dados de quem tem."""
    head = ["Relatório de Clientes;", ";", " ;", "DOCUMENTO;NOME;ENDEREÇO;BAIRRO;CIDADE;ESTADO;CEP;TELEFONE;E-MAIL;"]
    (tmp_path / "clientes.csv").write_bytes("\r\n".join(head + [
        ";OFICINA DO ZÉ;;;;;;;;",
        "11.222.333/0001-81;IMOBILIÁRIA SOL LTDA;Rua A, 1;Centro;Itajubá;MG;37.500-000;;;", ""]).encode("cp1252"))
    (tmp_path / "fornecedores.csv").write_bytes("\r\n".join(["Relatório de Fornecedores;"] + head[1:] + [
        "52.998.224/7-25;OFICINA DO ZÉ;Rua B, 2;Centro;Itajubá;MG;37.500-000;35 3622-1111;ze@exemplo.test;",
        "11.222.333/0001-81;IMOBILIÁRIA SOL LTDA.;Rua A, 1;Centro;Itajubá;MG;37.500-000;;;", ""]).encode("cp1252"))
    (tmp_path / "analitico-extra.csv").write_bytes("\r\n".join([
        "Relatório de Movimentos;", "Período de 01/01/2000 a 31/12/2030;", " ;",
        "DATA;DOCUMENTO;DESCRIÇÃO;NOME;VALOR;MOVSIT;VENCIMENTO;OBSERVAÇÃO;CONTA;CENTRO DE CUSTO;TIPO;",
        "01/03/2026;;ALUGUEL;IMOBILIÁRIA SOL LTDA.;R$ 900,00;P;10/03/2026;;Banco Azul;;Desp;", ""]).encode("cp1252"))
    keep = [p for p in _all() if p.name not in ("clientes.csv", "fornecedores.csv")]
    r, _rep = _import(session, tmp_path, keep + [tmp_path / n for n in
                                                 ("clientes.csv", "fornecedores.csv", "analitico-extra.csv")])
    ze = session.scalars(select(Contact).where(Contact.name == "OFICINA DO ZÉ")).all()
    assert len(ze) == 1
    assert (ze[0].address, ze[0].phone, ze[0].email, ze[0].is_customer, ze[0].is_supplier) == \
        ("Rua B, 2", "35 3622-1111", "ze@exemplo.test", True, True)
    sol = session.scalars(select(Contact).where(Contact.document == "11222333000181")).all()
    assert len(sol) == 1 and sol[0].is_customer and sol[0].is_supplier
    aluguel = _entry(session, "ALUGUEL", date(2026, 3, 10))
    assert aluguel.contact_id == sol[0].id                         # o nome com ponto acha o mesmo contato
    assert "IMOBILIÁRIA SOL LTDA." not in r.contacts_created_from_text
    assert not any("documento" in w for w in r.warnings)
