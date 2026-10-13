from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, entries, sales, stock
from finora.services.sales import SaleData, SaleLine


def _setup(s, eid):
    bank = accounts.list_accounts(s, eid)[0].id
    az = stock.create_item(s, eid, name="Azeite 500 mL", kind="produced", unit="garrafa", sale_price=D("90"))
    mel = stock.create_item(s, eid, name="Mel 1 kg", kind="produced", unit="pote", sale_price=D("45"))
    stock.move(s, eid, item_id=az, kind="in", quantity="100", day=date(2026, 9, 1), unit_cost="30")
    stock.move(s, eid, item_id=mel, kind="in", quantity="20", day=date(2026, 9, 1), unit_cost="18")
    return bank, az, mel


def test_orcamento_confirmar_parcelas_e_margem(session, profile):
    s, eid = session, profile.id
    bank, az, mel = _setup(s, eid)
    d = SaleData(day=date(2026, 10, 5), contact="Empório Bom Gosto", account_id=bank, payment="Boleto",
                 installments=3, first_due=date(2026, 11, 5), discount=D("30"), freight=D("20"),
                 lines=[SaleLine(az, D("10"), D("90")), SaleLine(mel, D("4"), D("45"))])
    sid = sales.save(s, eid, d)
    assert stock.balance(s, eid, az) == D("100")                          # orçamento não mexe no estoque
    assert sales.confirm(s, sid) == 3
    assert stock.balance(s, eid, az) == D("90") and stock.balance(s, eid, mel) == D("16")
    parts = [e for e in entries.list_entries(s, eid, year=2026, month=1, period="all")
             if e.description.startswith("Venda — pedido 1")]
    assert len(parts) == 3 and sum(e.amount for e in parts) == D("1070.00")      # 900 + 180 − 30 + 20
    assert all(e.contact == "Empório Bom Gosto" and e.kind == "income" for e in parts)
    v = sales.list_sales(s, eid)[0]
    assert (v.number, v.status, v.total, v.received) == (1, "confirmed", D("1070.00"), D("0"))
    by_item = {r.name: r for r in sales.summary(s, eid, date(2026, 10, 1), date(2026, 10, 31))}
    assert by_item["Azeite 500 mL"].cost == D("300.00") and by_item["Mel 1 kg"].cost == D("72.00")
    assert sum(r.revenue for r in by_item.values()) == D("1070.00")
    with pytest.raises(ValueError, match="Só dá para alterar"):
        sales.save(s, eid, d, sid)


def test_estoque_insuficiente_doacao_e_cancelamento(session, profile):
    s, eid = session, profile.id
    bank, az, mel = _setup(s, eid)
    sid = sales.save(s, eid, SaleData(day=date(2026, 10, 5), account_id=bank,
                                      lines=[SaleLine(mel, D("25"), D("45"))]))
    with pytest.raises(ValueError, match="Estoque insuficiente de Mel"):
        sales.confirm(s, sid)
    doa = sales.save(s, eid, SaleData(day=date(2026, 10, 6), kind="donation", contact="Feira da paróquia",
                                      lines=[SaleLine(az, D("2"), D("0"))]))
    assert sales.confirm(s, doa) == 0 and stock.balance(s, eid, az) == D("98")    # doação: só estoque
    vista = sales.save(s, eid, SaleData(day=date(2026, 10, 7), account_id=bank, paid_now=True,
                                        lines=[SaleLine(az, D("1"), D("90"))]))
    sales.confirm(s, vista)
    assert sales.list_sales(s, eid, status="confirmed")[0].received == D("90.00")
    with pytest.raises(ValueError, match="já tem parcela recebida"):
        sales.cancel(s, vista)
    prazo = sales.save(s, eid, SaleData(day=date(2026, 10, 8), account_id=bank, installments=2,
                                        lines=[SaleLine(az, D("5"), D("90"))]))
    sales.confirm(s, prazo)
    sales.cancel(s, prazo)
    assert stock.balance(s, eid, az) == D("97")                           # voltou ao estoque
    assert not [e for e in entries.list_entries(s, eid, year=2026, month=1, period="all")
                if "pedido 4" in e.description]                           # parcelas foram para a lixeira
    with pytest.raises(ValueError, match="pelo menos um item"):
        sales.save(s, eid, SaleData(day=date(2026, 10, 8), lines=[]))
    with pytest.raises(ValueError, match="1 vez"):
        sales.save(s, eid, SaleData(day=date(2026, 10, 8), paid_now=True, installments=2,
                                    lines=[SaleLine(az, D("1"), D("90"))]))
