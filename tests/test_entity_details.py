"""Dados da entidade (como a conta controle do MCC): bairro, complemento, país e "usa centro de custo"."""
from decimal import Decimal as D

import pytest

from finora.services import entity_admin


def test_endereco_completo_no_cabecalho(session, profile):
    s, eid = session, profile.id
    entity_admin.update_details(s, eid, address="Estrada Velha, km 12", address2="Galpão 3", district="Zona Rural",
                                city="Maria da Fé", state="mg", zip_code="37517000", country="Brasil")
    det = entity_admin.details(s, eid)
    assert (det["address2"], det["district"], det["state"], det["zip_code"]) == \
        ("Galpão 3", "Zona Rural", "MG", "37517-000")
    head = entity_admin.letterhead(s, eid)
    assert head.address_line == "Estrada Velha, km 12, Galpão 3 — Zona Rural — Maria da Fé/MG — CEP 37517-000"
    entity_admin.update_details(s, eid, country="Portugal")
    assert entity_admin.letterhead(s, eid).address_line.endswith("— Portugal")             # Brasil não aparece
    with pytest.raises(ValueError, match="longo demais"):
        entity_admin.update_details(s, eid, district="x" * 81)
    with pytest.raises(ValueError, match="desconhecido"):
        entity_admin.update_details(s, eid, bairro="Centro")


def test_usa_centro_de_custo(session, profile):
    s, eid = session, profile.id
    assert entity_admin.uses_cost_centers(s, eid)                                         # padrão: usa
    entity_admin.set_uses_cost_centers(s, eid, False)
    assert not entity_admin.uses_cost_centers(s, eid)
