from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import production, sales, stock, accounts
from finora.services.production import Line, ProductionData
from finora.services.sales import SaleData, SaleLine


def _setup(s, eid):
    azeitona = stock.create_item(s, eid, name="Azeitona", kind="input", unit="kg")
    garrafa = stock.create_item(s, eid, name="Garrafa 500 mL", kind="input", unit="un")
    azeite = stock.create_item(s, eid, name="Azeite 500 mL", kind="produced", unit="garrafa", sale_price=D("90"))
    stock.move(s, eid, item_id=azeitona, kind="in", quantity="2000", day=date(2026, 9, 1), unit_cost="4")
    stock.move(s, eid, item_id=garrafa, kind="in", quantity="500", day=date(2026, 9, 1), unit_cost="3")
    return azeitona, garrafa, azeite


def test_lote_concluido_tira_insumos_e_poe_produto_com_custo(session, profile):
    s, eid = session, profile.id
    azeitona, garrafa, azeite = _setup(s, eid)
    d = ProductionData(name="Azeite safra 2026 – lote 1", day=date(2026, 10, 2), extra_cost=D("200"),
                       inputs=[Line(azeitona, D("1000")), Line(garrafa, D("300"))],
                       outputs=[Line(azeite, D("300"))])
    pid = production.save(s, eid, d)
    assert stock.balance(s, eid, azeitona) == D("2000")              # em andamento não mexe no estoque
    total, costs = production.estimate(s, eid, d)
    assert total == D("5100.00") and costs == [D("17.0000")]          # 4000 + 900 + 200 ÷ 300
    assert production.finish(s, pid) == D("5100.00")
    assert stock.balance(s, eid, azeitona) == D("1000") and stock.balance(s, eid, garrafa) == D("200")
    assert stock.balance(s, eid, azeite) == D("300") and stock.average_cost(s, eid, azeite) == D("17")
    v = production.list_productions(s, eid)[0]
    assert (v.number, v.status, v.total_cost, v.unit_cost) == (1, "done", D("5100.00"), D("17.0000"))
    assert v.yield_text == "30 garrafa por 100 kg"
    row = production.summary(s, eid, date(2026, 10, 1), date(2026, 10, 31))[0]
    assert (row.name, row.quantity, row.cost, row.unit_cost, row.batches) == ("Azeite 500 mL", D("300"),
                                                                               D("5100.00"), D("17.0000"), 1)
    with pytest.raises(ValueError, match="reabra o lote"):              # movimento do lote não sai avulso
        stock.delete_move(s, stock.history(s, eid, azeite)[0].id)
    with pytest.raises(ValueError, match="Reabra"):
        production.save(s, eid, d, pid)


def test_venda_usa_o_custo_da_producao_e_reabrir(session, profile):
    s, eid = session, profile.id
    azeitona, garrafa, azeite = _setup(s, eid)
    pid = production.save(s, eid, ProductionData(name="Lote", day=date(2026, 10, 2),
                                                 inputs=[Line(azeitona, D("1000")), Line(garrafa, D("300"))],
                                                 outputs=[Line(azeite, D("300"))]))
    production.finish(s, pid)
    bank = accounts.list_accounts(s, eid)[0].id
    sid = sales.save(s, eid, SaleData(day=date(2026, 10, 5), account_id=bank,
                                      lines=[SaleLine(azeite, D("10"), D("90"))]))
    sales.confirm(s, sid)
    by_item = sales.summary(s, eid, date(2026, 10, 1), date(2026, 10, 31))[0]
    assert by_item.cost == D("163.33")                                  # 10 × 16,3333 (4900 ÷ 300)
    with pytest.raises(ValueError, match="já saiu do estoque"):
        production.reopen(s, pid)
    sales.cancel(s, sid)
    production.reopen(s, pid)
    assert stock.balance(s, eid, azeitona) == D("2000") and stock.balance(s, eid, azeite) == D("0")
    assert production.get(s, pid).status == "open"
    production.delete(s, pid)
    assert production.list_productions(s, eid) == []


def test_validacoes_e_rateio_entre_produtos(session, profile):
    s, eid = session, profile.id
    azeitona, garrafa, azeite = _setup(s, eid)
    bagaco = stock.create_item(s, eid, name="Bagaço", kind="produced", unit="kg")
    base = dict(name="Lote", day=date(2026, 10, 2), inputs=[Line(azeitona, D("1000"))])
    with pytest.raises(ValueError, match="somar 100%"):
        production.save(s, eid, ProductionData(**base, outputs=[Line(azeite, D("100"), D("90")),
                                                                Line(bagaco, D("500"), D("5"))]))
    with pytest.raises(ValueError, match="todos os produtos"):
        production.save(s, eid, ProductionData(**base, outputs=[Line(azeite, D("100"), D("90")),
                                                                Line(bagaco, D("500"))]))
    with pytest.raises(ValueError, match="insumo e produto"):
        production.save(s, eid, ProductionData(**base, outputs=[Line(azeitona, D("10"))]))
    pid = production.save(s, eid, ProductionData(**base, outputs=[Line(azeite, D("100"), D("90")),
                                                                  Line(bagaco, D("500"), D("10"))]))
    production.finish(s, pid)
    assert stock.average_cost(s, eid, azeite) == D("36")                # 4000 × 90% ÷ 100
    assert stock.average_cost(s, eid, bagaco) == D("0.8")               # 4000 × 10% ÷ 500
    falta = production.save(s, eid, ProductionData(name="Grande", day=date(2026, 10, 3),
                                                   inputs=[Line(azeitona, D("5000"))], outputs=[Line(azeite, D("1"))]))
    with pytest.raises(ValueError, match="Falta Azeitona"):
        production.finish(s, falta)
