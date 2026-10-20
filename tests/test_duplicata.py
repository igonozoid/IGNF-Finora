"""Duplicata de venda mercantil / de prestação de serviços (Fase 3.13, do MCC)."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, contacts, entity_admin, entries, receipts
from finora.services.entries import EntryData


def test_duplicata_de_uma_serie(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    entity_admin.update_details(s, eid, city="Maria da Fé", state="MG")
    contacts.create(s, eid, name="Cooperativa Serra", person_type="PJ", document="11222333000181",
                    roles={"customer"}, details={"document2": "123456", "address": "Rua A, 10", "district": "Centro",
                                                 "city": "Itajubá", "state": "MG", "zip_code": "37500-000"})
    ids = entries.create(s, eid, EntryData(kind="income", description="Venda de azeite", amount=D("3000"),
                                           due_date=date(2026, 11, 10), account_id=bank, contact="Cooperativa Serra",
                                           document_no="NF 77", repeat="installments", times=3))
    d = receipts.build_duplicata(s, ids[1], "mercantil", issued=date(2026, 10, 21))
    assert (d.number, d.invoice, d.amount, d.invoice_amount, d.due) == \
        ("NF 77-2/3", "NF 77", D("1000.00"), D("3000.00"), date(2026, 12, 10))
    assert (d.sacado, d.sacado_doc, d.sacado_ie, d.sacado_address, d.sacado_city) == \
        ("Cooperativa Serra", "11.222.333/0001-81", "123456", "Rua A, 10, Centro", "Itajubá/MG — CEP 37500-000")
    assert (d.place, d.issued, d.title) == ("Maria da Fé/MG", date(2026, 10, 21), "Duplicata de venda mercantil")
    assert d.amount_words == "mil reais" and "VENDA MERCANTIL" in d.acceptance and profile.name in d.acceptance
    serv = receipts.build_duplicata(s, ids[0], "servico", invoice="FAT-9", place="Itajubá/MG")
    assert (serv.number, serv.place, serv.title) == ("FAT-9-1/3", "Itajubá/MG", "Duplicata de prestação de serviços")
    assert "PRESTAÇÃO DE SERVIÇOS" in serv.acceptance


def test_duplicata_so_de_receita_com_contato(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    (exp,) = entries.create(s, eid, EntryData(kind="expense", description="Luz", amount=D("100"),
                                              due_date=date(2026, 11, 1), account_id=bank, contact="Enel"))
    (alone,) = entries.create(s, eid, EntryData(kind="income", description="Venda", amount=D("100"),
                                                due_date=date(2026, 11, 1), account_id=bank))
    (one,) = entries.create(s, eid, EntryData(kind="income", description="Venda", amount=D("250"),
                                              due_date=date(2026, 11, 1), account_id=bank, contact="Cliente"))
    with pytest.raises(ValueError, match="só para receitas"):
        receipts.build_duplicata(s, exp)
    with pytest.raises(ValueError, match="contato"):
        receipts.build_duplicata(s, alone)
    with pytest.raises(ValueError):
        receipts.build_duplicata(s, one, "boleto")
    d = receipts.build_duplicata(s, one)
    assert (d.number, d.invoice_amount) == (f"{one:06d}", D("250.00"))      # sem documento: o nº do lançamento
