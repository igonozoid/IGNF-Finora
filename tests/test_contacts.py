from datetime import date
from decimal import Decimal as D

import pytest

from finora.core import documents
from finora.services import accounts, contacts, entries
from finora.services.entries import EntryData

CPF = "529.982.247-25"          # válido
CNPJ = "11.222.333/0001-81"     # válido


@pytest.mark.parametrize("doc, kind, ok", [
    (CPF, "PF", True), ("52998224724", "PF", False), ("111.111.111-11", "PF", False), ("123", "PF", False),
    (CNPJ, "PJ", True), ("11222333000180", "PJ", False), ("00.000.000/0000-00", "PJ", False),
    (CPF, "PJ", False),
])
def test_validacao_documento(doc, kind, ok):
    assert documents.is_valid(doc, kind) is ok


def test_formatar_documento():
    assert documents.fmt("52998224725") == CPF
    assert documents.fmt("11222333000181") == CNPJ
    assert documents.fmt("123") == "123"


def test_criar_listar_e_filtrar(session, profile):
    s, eid = session, profile.id
    contacts.create(s, eid, name="Enel", person_type="PJ", document=CNPJ, roles={"supplier"})
    contacts.create(s, eid, name="Maria Diarista", document=CPF, roles={"employee", "supplier"})
    contacts.create(s, eid, name="empresa x", roles={"customer"})
    lst = contacts.list_contacts(s, eid)
    assert [c.name for c in lst] == ["empresa x", "Enel", "Maria Diarista"]
    enel = lst[1]
    assert enel.document == "11222333000181" and enel.document_fmt == CNPJ and enel.initials == "E"
    assert lst[2].initials == "MD" and lst[2].roles == {"employee", "supplier"}
    assert [c.name for c in contacts.list_contacts(s, eid, role="supplier")] == ["Enel", "Maria Diarista"]
    assert [c.name for c in contacts.list_contacts(s, eid, search="maria")] == ["Maria Diarista"]
    assert [c.name for c in contacts.list_contacts(s, eid, search="11.222")] == ["Enel"]
    assert contacts.counts(s, eid) == {"all": 3, "customer": 1, "supplier": 2, "employee": 1}


def test_validacoes(session, profile):
    s, eid = session, profile.id
    contacts.create(s, eid, name="Enel", person_type="PJ", document=CNPJ)
    with pytest.raises(ValueError, match="nome"):
        contacts.create(s, eid, name=" ")
    with pytest.raises(ValueError, match="CPF inválido"):
        contacts.create(s, eid, name="A", document="123.456.789-00")
    with pytest.raises(ValueError, match="Já existe um contato chamado"):
        contacts.create(s, eid, name="ENEL")
    with pytest.raises(ValueError, match="documento"):
        contacts.create(s, eid, name="Outra", person_type="PJ", document="11222333000181")


def test_editar(session, profile):
    s, eid = session, profile.id
    cid = contacts.create(s, eid, name="Joao", roles={"customer"})
    contacts.update(s, cid, name="João Silva", person_type="PF", document=CPF, roles={"supplier"})
    c = contacts.list_contacts(s, eid)[0]
    assert (c.name, c.document, c.roles) == ("João Silva", "52998224725", {"supplier"})


def test_lancamento_cria_contato_com_papel_e_bloqueia_exclusao(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    entries.create(s, eid, EntryData(kind="expense", description="Luz", amount=D("100"),
                                     due_date=date(2026, 10, 5), account_id=bank, contact="Enel"))
    entries.create(s, eid, EntryData(kind="income", description="Reembolso", amount=D("20"),
                                     due_date=date(2026, 10, 9), account_id=bank, contact="enel"))
    (c,) = contacts.list_contacts(s, eid)
    assert c.roles == {"supplier", "customer"} and c.entries == 2 and c.last_date == date(2026, 10, 9)
    with pytest.raises(ValueError, match="2 lançamentos"):
        contacts.delete(s, c.id)
    other = contacts.create(s, eid, name="Sem uso")
    contacts.delete(s, other)
    assert [x.name for x in contacts.list_contacts(s, eid)] == ["Enel"]


def test_dados_extras_do_contato(session, profile):
    s, eid = session, profile.id
    cid = contacts.create(s, eid, name="Maria", details={
        "phone": "(19) 99999-1234", "email": "maria@exemplo.com", "zip_code": "13010050", "address": "Rua A, 10",
        "city": "Campinas", "state": "sp", "pix_key": "maria@exemplo.com", "bank_info": "Itaú · 0412 · 55210-3",
        "notes": "Vem às terças"})
    c = contacts.list_contacts(s, eid)[0]
    assert (c.get("zip_code"), c.get("state"), c.get("phone")) == ("13010-050", "SP", "(19) 99999-1234")
    assert [x.name for x in contacts.list_contacts(s, eid, search="99999")] == ["Maria"]       # pelo telefone
    assert [x.name for x in contacts.list_contacts(s, eid, search="exemplo.com")] == ["Maria"] # pelo e-mail
    contacts.update(s, cid, name="Maria", person_type="PF", document=None, roles=set(),
                    details={"city": "", "notes": "Agora às quartas"})
    c = contacts.list_contacts(s, eid)[0]
    assert c.get("city") == "" and c.get("notes") == "Agora às quartas" and c.get("phone") == "(19) 99999-1234"


@pytest.mark.parametrize("details, msg", [
    ({"email": "maria.exemplo.com"}, "E-mail"), ({"state": "XX"}, "UF"), ({"zip_code": "123"}, "CEP"),
    ({"idade": "30"}, "desconhecido"),
])
def test_dados_extras_invalidos(session, profile, details, msg):
    with pytest.raises(ValueError, match=msg):
        contacts.create(session, profile.id, name="X", details=details)
