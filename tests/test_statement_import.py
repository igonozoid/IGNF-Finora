from datetime import date
from decimal import Decimal as D

import pytest
from openpyxl import Workbook

from finora.services import accounts, reconcile
from finora.services import statement_import as si

ITAU = """Extrato conta corrente
Agência 1234 Conta 56789-0
Data;Lançamento;Valor (R$);Saldo (R$)
01/10/2026;SALDO ANTERIOR;;1.000,00
02/10/2026;PIX RECEBIDO JOAO;150,00;1.150,00
03/10/2026;UBER *TRIP;-23,90;1.126,10
03/10/2026;UBER *TRIP;-23,90;1.102,20
05/10/2026;PAG BOLETO ENEL;-180,40;921,80
""".encode("cp1252")


def test_valores_e_datas_de_varios_bancos():
    assert si.parse_amount("1.234,56") == D("1234.56") and si.parse_amount("1,234.56") == D("1234.56")
    assert si.parse_amount("(50,00)") == D("-50.00") and si.parse_amount("50,00 D") == D("-50.00")
    assert si.parse_amount("R$ -10,00") == D("-10.00") and si.parse_amount("−3,5") == D("-3.50")
    assert si.parse_amount("12.5") == D("12.50") and si.parse_amount("1.234") == D("1234.00")
    assert si.parse_amount("abc") is None and si.parse_amount("") is None
    assert si.parse_date("05/10/2026") == date(2026, 10, 5) and si.parse_date("2026-10-05") == date(2026, 10, 5)
    assert si.parse_date("05/10/26") == date(2026, 10, 5) and si.parse_date("46300") == date(2026, 10, 5)


def test_csv_adivinha_colunas_pula_saldo_e_nao_duplica(session, profile):
    rows = si.read_table(ITAU, "extrato.csv")
    m = si.guess(rows)
    assert (m.header_row, m.date_col, m.desc_col, m.amount_col) == (2, 0, 1, 2)
    parsed = si.parse(rows, m)
    assert [(ln.posted.day, ln.amount) for ln in parsed.lines] == [(2, D("150.00")), (3, D("-23.90")),
                                                                    (3, D("-23.90")), (5, D("-180.40"))]
    assert parsed.skipped == 1 and len({ln.fitid for ln in parsed.lines}) == 4   # duas Uber iguais = duas linhas
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    assert reconcile.import_lines(s, eid, bank, parsed.lines).new == 4
    again = reconcile.import_lines(s, eid, bank, si.parse(si.read_table(ITAU, "x.csv"), m).lines)
    assert (again.new, again.repeated) == (0, 4)


def test_excel_de_fatura_com_entrada_e_saida(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Data", "Descrição", "Crédito", "Débito"])
    ws.append([date(2026, 10, 1), "Mercado Bom Preço", None, 85.5])
    ws.append([date(2026, 10, 2), "Estorno", 10, None])
    path = tmp_path / "fatura.xlsx"
    wb.save(path)
    rows = si.read_table(path.read_bytes(), "fatura.xlsx")
    m = si.guess(rows)
    assert (m.in_col, m.out_col, m.amount_col) == (2, 3, -1)
    assert [ln.amount for ln in si.parse(rows, m).lines] == [D("-85.50"), D("10.00")]
    m2 = si.Mapping(header_row=0, date_col=0, desc_col=1, amount_col=3, invert=True)   # compras positivas
    assert [ln.amount for ln in si.parse(rows, m2).lines] == [D("-85.50")]
    with pytest.raises(ValueError):
        si.parse(rows, si.Mapping())
    with pytest.raises(ValueError, match="xls"):
        si.read_table(b"x", "velho.xls")
