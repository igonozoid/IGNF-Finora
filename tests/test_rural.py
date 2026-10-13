from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import rural, stock
from finora.services.rural import ActivityData, Use


def _setup(s, eid):
    farm = rural.save_farm(s, eid, name="Singolare", city="Pinheiro Machado")
    pomar = rural.save_area(s, eid, farm_id=farm, name="Pomar 1", kind="orchard", crop="Oliveira arbequina",
                            hectares="10", units=3000)
    adubo = stock.create_item(s, eid, name="Adubo NPK", kind="input", unit="kg")
    azeitona = stock.create_item(s, eid, name="Azeitona", kind="input", unit="kg")
    stock.move(s, eid, item_id=adubo, kind="in", quantity="1000", day=date(2026, 1, 5), unit_cost="3")
    return farm, pomar, adubo, azeitona


def test_atividades_consomem_insumo_e_colheita_leva_o_custo(session, profile):
    s, eid = session, profile.id
    farm, pomar, adubo, azeitona = _setup(s, eid)
    rural.save_activity(s, eid, ActivityData(pomar, date(2026, 2, 1), "fertilizing", "Adubação de cobertura",
                                             inputs=[Use(adubo, D("400"))], other_cost=D("300")))
    rural.save_activity(s, eid, ActivityData(pomar, date(2026, 3, 1), "occurrence", "Geada fraca"))
    assert stock.balance(s, eid, adubo) == D("600")
    assert rural.areas(s, eid)[0].pending_cost == D("1500.00")           # 400 × 3 + 300
    d = ActivityData(pomar, date(2026, 4, 10), "harvest", "Colheita manual", harvest=[Use(azeitona, D("3000"))],
                     other_cost=D("600"))
    assert rural.suggested_harvest_cost(s, eid, d) == D("2100.00")
    hid = rural.save_activity(s, eid, d)
    assert stock.balance(s, eid, azeitona) == D("3000") and stock.average_cost(s, eid, azeitona) == D("0.7")
    assert rural.areas(s, eid)[0].pending_cost == D("0")
    row = rural.area_costs(s, eid, date(2026, 1, 1), date(2026, 12, 31))[0]
    assert (row.area, row.total, row.per_ha, row.harvest_cost, row.activities) == (
        "Singolare › Pomar 1", D("2100.00"), D("210.00"), D("2100.00"), 3)
    assert row.harvested == "Azeitona 3.000 kg"
    acts = rural.list_activities(s, eid, kind="harvest")
    assert len(acts) == 1 and acts[0].text("harvest") == "Azeitona 3.000 kg"
    with pytest.raises(ValueError, match="altere ou exclua a atividade"):
        stock.delete_move(s, stock.history(s, eid, azeitona)[0].id)
    stock.move(s, eid, item_id=azeitona, kind="out", quantity="2500", day=date(2026, 4, 11))
    with pytest.raises(ValueError, match="já saiu do estoque"):
        rural.delete_activity(s, hid)


def test_editar_excluir_e_validacoes(session, profile):
    s, eid = session, profile.id
    farm, pomar, adubo, azeitona = _setup(s, eid)
    aid = rural.save_activity(s, eid, ActivityData(pomar, date(2026, 2, 1), "fertilizing",
                                                   inputs=[Use(adubo, D("400"))]))
    rural.save_activity(s, eid, ActivityData(pomar, date(2026, 2, 1), "fertilizing", inputs=[Use(adubo, D("100"))]),
                        aid)
    assert stock.balance(s, eid, adubo) == D("900")                     # alterar refaz o movimento
    with pytest.raises(ValueError, match="Falta Adubo"):
        rural.save_activity(s, eid, ActivityData(pomar, date(2026, 2, 2), "fertilizing",
                                                 inputs=[Use(adubo, D("5000"))]))
    with pytest.raises(ValueError, match="o que foi colhido"):
        rural.save_activity(s, eid, ActivityData(pomar, date(2026, 4, 1), "harvest"))
    with pytest.raises(ValueError, match="mesmo nome|com esse nome"):
        rural.save_area(s, eid, farm_id=farm, name="pomar 1")
    hid = rural.save_activity(s, eid, ActivityData(pomar, date(2026, 4, 1), "harvest",
                                                   harvest=[Use(azeitona, D("1000"))], harvest_cost=D("100")))
    assert stock.average_cost(s, eid, azeitona) == D("0.1")              # custo informado à mão
    assert rural.areas(s, eid)[0].pending_cost == D("200.00")            # 300 − 100: o resto fica para a próxima
    rural.delete_activity(s, hid)
    rural.delete_activity(s, aid)
    assert stock.balance(s, eid, adubo) == D("1000") and stock.balance(s, eid, azeitona) == D("0")
    assert rural.list_activities(s, eid) == []
