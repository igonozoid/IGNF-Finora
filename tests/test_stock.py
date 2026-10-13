from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, entries, period_lock, stock


def test_cadastro_entrada_saida_e_custo_medio(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    garrafa = stock.create_item(s, eid, name="Garrafa 500 mL", kind="input", unit="un", min_stock=D("100"))
    with pytest.raises(ValueError, match="Já existe"):
        stock.create_item(s, eid, name="garrafa 500 ml", kind="input", unit="un")
    stock.move(s, eid, item_id=garrafa, kind="in", quantity=D("200"), day=date(2026, 9, 1), unit_cost=D("2.00"),
               contact="Vidraria Sul", payable={"account_id": bank, "due_date": date(2026, 9, 30)})
    stock.move(s, eid, item_id=garrafa, kind="in", quantity="100", day=date(2026, 9, 10), unit_cost="2.60")
    it = stock.get_item(s, garrafa)
    assert it.balance == D("300") and it.avg_cost == D("2.2000") and it.value == D("660.00")
    compra = next(e for e in entries.list_entries(s, eid, year=2026, month=9) if e.description.startswith("Compra"))
    assert compra.amount == D("400.00") and compra.contact == "Vidraria Sul" and not compra.is_paid
    stock.move(s, eid, item_id=garrafa, kind="out", quantity="250", day=date(2026, 9, 15), notes="Envase")
    it = stock.get_item(s, garrafa)
    assert it.balance == D("50") and it.below_min and stock.low_stock(s, eid)[0].id == garrafa
    with pytest.raises(ValueError, match="Saldo insuficiente"):
        stock.move(s, eid, item_id=garrafa, kind="loss", quantity="51", day=date(2026, 9, 16))
    hist = stock.history(s, eid, garrafa)
    assert [h.balance for h in hist] == [D("50"), D("300"), D("200")]            # mais novo primeiro
    assert stock.fmt_qty(D("1234.500"), "kg") == "1.234,5 kg"


def test_inventario_transferencia_e_periodo_fechado(session, profile):
    s, eid = session, profile.id
    papel = stock.create_item(s, eid, name="Papel A4 (resma)", kind="material", unit="pct")
    galpao = stock.save_location(s, eid, "Galpão")
    principal = stock.default_location(s, eid)
    stock.move(s, eid, item_id=papel, kind="in", quantity="10", day=date(2026, 10, 1), unit_cost="25")
    stock.adjust(s, eid, item_id=papel, counted="8", day=date(2026, 10, 5))         # sumiram 2
    assert stock.balance(s, eid, papel) == D("8")
    with pytest.raises(ValueError, match="nada a ajustar"):
        stock.adjust(s, eid, item_id=papel, counted="8", day=date(2026, 10, 5))
    stock.transfer(s, eid, item_id=papel, quantity="3", day=date(2026, 10, 6), from_id=principal, to_id=galpao)
    assert stock.balance(s, eid, papel, galpao) == D("3") and stock.balance(s, eid, papel, principal) == D("5")
    with pytest.raises(ValueError, match="ainda tem itens"):
        stock.save_location(s, eid, "Galpão", galpao, is_active=False)
    move_id = stock.history(s, eid, papel)[0].id
    stock.delete_move(s, move_id)                                                     # a transferência sai inteira
    assert stock.balance(s, eid, papel, galpao) == D("0") and stock.balance(s, eid, papel) == D("8")
    period_lock.set_lock(s, eid, date(2026, 9, 30))
    with pytest.raises(ValueError, match="fechado"):
        stock.move(s, eid, item_id=papel, kind="out", quantity="1", day=date(2026, 9, 30))
