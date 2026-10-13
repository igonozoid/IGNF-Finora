from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, entries, livestock, rural, stock
from finora.services.livestock import EventData, Use


def _setup(s, eid):
    farm = rural.save_farm(s, eid, name="El Rocio II")
    p1 = rural.save_area(s, eid, farm_id=farm, name="Piquete 1", kind="pasture", crop="Tifton", hectares="20")
    p2 = rural.save_area(s, eid, farm_id=farm, name="Piquete 2", kind="pasture", hectares="15")
    vacas = livestock.save_lot(s, eid, name="Vacas de cria", category="Vaca", area_id=p1)
    bez = livestock.save_lot(s, eid, name="Bezerros 2026", category="Bezerro", area_id=p1)
    vacina = stock.create_item(s, eid, name="Vacina aftosa", kind="input", unit="dose")
    sal = stock.create_item(s, eid, name="Sal mineral", kind="input", unit="kg")
    stock.move(s, eid, item_id=vacina, kind="in", quantity="200", day=date(2026, 1, 2), unit_cost="2.5")
    stock.move(s, eid, item_id=sal, kind="in", quantity="500", day=date(2026, 1, 2), unit_cost="4")
    return p1, p2, vacas, bez, vacina, sal


def test_rebanho_por_lote_compra_nascimento_venda_e_custos(session, profile):
    s, eid = session, profile.id
    p1, p2, vacas, bez, vacina, sal = _setup(s, eid)
    bank = accounts.list_accounts(s, eid)[0].id
    livestock.save_event(s, eid, EventData(vacas, date(2026, 1, 10), "purchase", heads=50, weight=D("420"),
                                           value=D("150000"), contact="Leilão Pampa",
                                           finance={"account_id": bank, "due_date": date(2026, 2, 10)}))
    livestock.save_event(s, eid, EventData(bez, date(2026, 3, 1), "birth", heads=40))
    livestock.save_event(s, eid, EventData(vacas, date(2026, 3, 5), "death", heads=1, description="Picada de cobra"))
    livestock.save_event(s, eid, EventData(vacas, date(2026, 3, 10), "health", inputs=[Use(vacina, D("49"))],
                                           other_cost=D("200"), description="Aftosa"))
    livestock.save_event(s, eid, EventData(vacas, date(2026, 4, 1), "feeding", inputs=[Use(sal, D("100"))]))
    livestock.save_event(s, eid, EventData(vacas, date(2026, 4, 2), "move", area_id=p2))
    livestock.save_event(s, eid, EventData(bez, date(2026, 6, 1), "weighing", heads=40, weight=D("150")))
    livestock.save_event(s, eid, EventData(bez, date(2026, 7, 1), "weighing", heads=40, weight=D("180")))
    livestock.save_event(s, eid, EventData(bez, date(2026, 8, 1), "sale", heads=10, value=D("25000"),
                                           contact="Frigorífico Sul",
                                           finance={"account_id": bank, "paid": True}))
    by = {lv.name: lv for lv in livestock.lots(s, eid)}
    assert by["Vacas de cria"].heads == 49 and by["Vacas de cria"].area == "El Rocio II › Piquete 2"
    assert by["Bezerros 2026"].heads == 30 and by["Bezerros 2026"].weight == D("180")
    assert by["Bezerros 2026"].daily_gain == D("1.000")                  # 30 kg em 30 dias
    assert stock.balance(s, eid, vacina) == D("151") and stock.balance(s, eid, sal) == D("400")
    contas = {e.description: e for e in entries.list_entries(s, eid, year=2026, month=1, period="all")}
    assert contas["Compra de animais: 50 cab. (Vacas de cria)"].amount == D("150000.00")
    venda = contas["Venda de animais: 10 cab. (Bezerros 2026)"]
    assert venda.kind == "income" and venda.status == "paid"
    rows = {r.lot: r for r in livestock.lot_costs(s, eid, date(2026, 1, 1), date(2026, 12, 31))}
    v = rows["Vacas de cria"]
    assert (v.bought, v.deaths, v.purchases, v.inputs_cost, v.other_cost) == (50, 1, D("150000.00"), D("522.50"),
                                                                              D("200.00"))
    assert v.cost == D("722.50") and v.per_head == D("14.74")
    b = rows["Bezerros 2026"]
    assert (b.births, b.sold, b.sales) == (40, 10, D("25000.00"))
    with pytest.raises(ValueError, match="tem 30 cabeça"):
        livestock.save_event(s, eid, EventData(bez, date(2026, 9, 1), "death", heads=31))
    with pytest.raises(ValueError, match="registro em Pecuária"):
        stock.delete_move(s, stock.history(s, eid, sal)[0].id)


def test_transferencia_edicao_e_exclusao(session, profile):
    s, eid = session, profile.id
    p1, p2, vacas, bez, vacina, sal = _setup(s, eid)
    bank = accounts.list_accounts(s, eid)[0].id
    nasc = livestock.save_event(s, eid, EventData(vacas, date(2026, 3, 1), "birth", heads=20))
    tid = livestock.save_event(s, eid, EventData(vacas, date(2026, 9, 1), "transfer", heads=15, to_lot_id=bez,
                                                 description="Desmama"))
    by = {lv.name: lv.heads for lv in livestock.lots(s, eid)}
    assert by == {"Vacas de cria": 5, "Bezerros 2026": 15}
    ev = [e for e in livestock.list_events(s, eid, lot_id=bez)][0]
    assert ev.kind == "transfer_in" and ev.detail.startswith("de Vacas de cria")
    assert livestock.get_event(s, ev.id).view.id == tid                   # edita-se pelo lado que saiu
    livestock.save_event(s, eid, EventData(vacas, date(2026, 9, 1), "transfer", heads=10, to_lot_id=bez), tid)
    by = {lv.name: lv.heads for lv in livestock.lots(s, eid)}
    assert by == {"Vacas de cria": 10, "Bezerros 2026": 10}
    with pytest.raises(ValueError, match="negativas"):
        livestock.delete_event(s, nasc)                                   # já saíram 10 desses animais
    tids = [e.id for e in livestock.list_events(s, eid, kind="transfer")]
    livestock.delete_event(s, tids[0])
    assert {lv.name: lv.heads for lv in livestock.lots(s, eid)} == {"Vacas de cria": 20, "Bezerros 2026": 0}
    compra = livestock.save_event(s, eid, EventData(bez, date(2026, 10, 1), "purchase", heads=5, value=D("9000"),
                                                    finance={"account_id": bank, "due_date": date(2026, 11, 1)}))
    entry_id = livestock.get_event(s, compra).view.entry_id
    livestock.delete_event(s, compra)                                     # conta em aberto vai para a lixeira
    from finora.services import trash
    assert trash.get(s, entry_id).deleted_at is not None
    with pytest.raises(ValueError, match="ainda tem animais"):
        livestock.save_lot(s, eid, name="Vacas de cria", is_active=False, lot_id=vacas)
