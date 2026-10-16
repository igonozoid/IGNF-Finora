"""Mesclar contatos duplicados (Fase 2.13)."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from finora.models import AuditLog, CategoryRule, Contact, Entry, ImportMap
from finora.services import accounts, contacts, entity_admin, entries, trash
from finora.services.entries import EntryData

CNPJ = "11222333000181"


def _entry(s, eid, contact, desc="Luz", kind="expense"):
    bank = accounts.list_accounts(s, eid)[0].id
    return entries.create(s, eid, EntryData(kind=kind, description=desc, amount=D("100"), due_date=date(2026, 10, 5),
                                            account_id=bank, contact=contact))


def _contact(s, eid, name):
    return s.scalar(select(Contact.id).where(Contact.entity_id == eid, Contact.name == name))


def test_mesclar_move_tudo_e_completa_o_cadastro(session, profile):
    s, eid = session, profile.id
    keep = contacts.create(s, eid, name="Energia Compartilhada S.A.", person_type="PJ", roles={"supplier"},
                           details={"phone": "3533330000"})
    _entry(s, eid, "Energia Compartilhada S.A.")
    _entry(s, eid, "ENERGIA COMPARTILHADA", desc="Luz julho")
    _entry(s, eid, "ENERGIA COMPARTILHADA", desc="Reembolso", kind="income")
    drop = _contact(s, eid, "ENERGIA COMPARTILHADA")
    c = s.get(Contact, drop)
    c.document, c.person_type, c.email, c.needs_review = CNPJ, "PJ", "conta@energia.test", True
    gone = s.scalar(select(Entry.id).where(Entry.description == "Luz julho"))
    trash.move(s, [s.get(Entry, gone)])                                  # o da lixeira também passa
    s.add(CategoryRule(entity_id=eid, text="ENERGIA", contact_id=drop))
    s.add(ImportMap(source="mcc", kind="pessoas", source_id="7", target=str(drop)))
    s.commit()
    assert contacts.duplicates(s, eid, keep) == [drop]                    # sem acento, pontuação nem "S.A."

    r = contacts.merge(s, keep, drop)
    assert (r.entries, r.others) == (2, 1)                               # o 1º já era do mantido
    assert s.get(Contact, drop) is None
    k = s.get(Contact, keep)
    assert (k.document, k.email, k.phone, k.is_customer, k.is_supplier, k.needs_review) == \
        (CNPJ, "conta@energia.test", "3533330000", True, True, False)
    assert trash.get(s, gone).contact_id == keep
    assert s.scalar(select(CategoryRule.contact_id)) == keep
    assert s.scalar(select(ImportMap.target).where(ImportMap.source_id == "7")) == str(keep)
    (c,) = contacts.list_contacts(s, eid)
    assert c.entries == 2                                                # os 2 fora da lixeira
    log = s.scalars(select(AuditLog.summary).where(AuditLog.action == "note")).all()
    assert any("Mesclou" in x and "2 lançamento(s)" in x for x in log)


def test_mesclar_recusa(session, profile, plus):
    s, eid = session, profile.id
    a = contacts.create(s, eid, name="Ana", person_type="PJ", document=CNPJ)
    b = contacts.create(s, eid, name="Ana Maria", person_type="PF", document="52998224725")
    with pytest.raises(ValueError, match="diferentes"):
        contacts.merge(s, a, b)
    with pytest.raises(ValueError, match="dois contatos diferentes"):
        contacts.merge(s, a, a)
    other = entity_admin.create(s, name="Outra", person_type="PF")
    shared = contacts.create(s, other, name="Contador", shared=True)
    mine = contacts.create(s, eid, name="Contador da casa")
    with pytest.raises(ValueError, match="compartilhado"):
        contacts.merge(s, mine, shared)                                  # o compartilhado não some
    contacts.merge(s, shared, mine)                                      # ao contrário pode
    assert s.get(Contact, mine) is None
