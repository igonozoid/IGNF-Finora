"""Marca "a revisar" em contato, categoria e centro criados fora do cadastro (Fase 4.6)."""
from datetime import date
from decimal import Decimal as D

from finora.services import accounts, categories, contacts, cost_centers, entries
from finora.services.entries import EntryData


def test_contato_criado_no_lancamento_fica_a_revisar(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    entries.create(s, eid, EntryData(kind="expense", description="Luz", amount=D("10"), due_date=date(2026, 10, 1),
                                     account_id=bank, contact="Enel"))
    enel = contacts.list_contacts(s, eid, role="review")
    assert [c.name for c in enel] == ["Enel"]
    contacts.update(s, enel[0].id, name="Enel", person_type="PJ", document=None, roles={"supplier"})
    assert contacts.counts(s, eid)["review"] == 0


def test_categoria_a_revisar_filtro_e_salvar(session, profile):
    s, eid = session, profile.id
    group = categories.tree(s, eid)[-1]
    cid = categories.create(s, eid, name="Nova do lançamento", parent_id=group.id, needs_review=True)
    assert categories.review_count(s, eid) == 1
    roots = categories.tree(s, eid, only_review=True)
    assert [r.id for r in roots] == [group.id] and [c.id for c in roots[0].children] == [cid]
    assert roots[0].children[0].needs_review
    categories.update(s, cid, name="Nova do lançamento")
    assert categories.review_count(s, eid) == 0 and categories.tree(s, eid, only_review=True) == []


def test_centro_a_revisar_filtro_e_salvar(session, profile):
    s, eid = session, profile.id
    a = cost_centers.create(s, eid, "Obra A", needs_review=True)
    cost_centers.create(s, eid, "Obra B")
    assert cost_centers.review_count(s, eid) == 1
    assert [c.name for c in cost_centers.list_centers(s, eid, 2026, 10, only_review=True)] == ["Obra A"]
    cost_centers.update(s, a, "Obra A", None)
    assert cost_centers.review_count(s, eid) == 0
