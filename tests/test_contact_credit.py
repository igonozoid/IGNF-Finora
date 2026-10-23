"""Crédito do contato (Fase 4.1): limite, consulta, pendência, nome da mãe, classificação e frequência."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import contacts


def _view(s, eid, cid):
    return next(c for c in contacts.list_contacts(s, eid) if c.id == cid)


def test_guarda_e_le_o_credito(session, profile):
    s, eid = session, profile.id
    cid = contacts.create(s, eid, name="Maria", credit={
        "credit_limit": "5.000,00", "credit_checked_on": "10/03/2026", "credit_pending": True,
        "credit_pending_where": " Serasa ", "mother_name": "Ana", "rating": "bom", "purchase_frequency": "mensal"})
    cr = _view(s, eid, cid).credit
    assert cr == {"credit_limit": D("5000.00"), "credit_checked_on": date(2026, 3, 10), "credit_pending": True,
                  "credit_pending_where": "Serasa", "mother_name": "Ana", "rating": "bom",
                  "purchase_frequency": "mensal"}


def test_sem_pendencia_o_local_some_e_pj_nao_tem_mae(session, profile):
    s, eid = session, profile.id
    cid = contacts.create(s, eid, name="Loja", credit={"credit_pending": True, "credit_pending_where": "SPC",
                                                        "mother_name": "Ana"})
    contacts.update(s, cid, name="Loja", person_type="PJ", document=None, roles=set(),
                    credit={"credit_pending": False, "credit_pending_where": "SPC"})
    cr = _view(s, eid, cid).credit
    assert cr["credit_pending"] is False and cr["credit_pending_where"] is None and cr["mother_name"] is None


def test_atualizar_sem_credito_nao_mexe(session, profile):
    s, eid = session, profile.id
    cid = contacts.create(s, eid, name="Maria", credit={"credit_limit": D("100")})
    contacts.update(s, cid, name="Maria", person_type="PF", document=None, roles=set(), credit=None)
    assert _view(s, eid, cid).credit["credit_limit"] == D("100.00")


@pytest.mark.parametrize("credit, msg", [
    ({"credit_limit": "-5"}, "negativo"),
    ({"credit_limit": "abc"}, "Limite"),
    ({"credit_checked_on": "31/02/2026"}, "Data inválida"),
    ({"credit_checked_on": "01/01/2999"}, "futuro"),
    ({"rating": "excelente"}, "Opção"),
])
def test_validacoes(session, profile, credit, msg):
    with pytest.raises(ValueError, match=msg):
        contacts.create(session, profile.id, name="X", credit=credit)


def test_mesclar_leva_o_credito(session, profile):
    s, eid = session, profile.id
    keep = contacts.create(s, eid, name="Enel")
    drop = contacts.create(s, eid, name="ENEL SA", credit={"credit_limit": D("300"), "rating": "otimo"})
    contacts.merge(s, keep, drop)
    cr = _view(s, eid, keep).credit
    assert cr["credit_limit"] == D("300.00") and cr["rating"] == "otimo"
