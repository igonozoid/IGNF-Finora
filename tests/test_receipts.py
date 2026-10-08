from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, contacts, entries, receipts
from finora.services.entries import EntryData


@pytest.fixture
def ctx(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    contacts.create(s, eid, name="Maria Diarista", document="52998224725")

    def add(**kw):
        base = dict(kind="expense", description="Faxina de outubro", amount=D("350"), due_date=date(2026, 10, 10),
                    account_id=bank, contact="Maria Diarista", paid=True, paid_date=date(2026, 10, 11))
        base.update(kw)
        return entries.create(s, eid, EntryData(**base))[0]
    return dict(s=s, eid=eid, bank=bank, add=add)


def test_recibo_de_despesa_quem_assina_e_o_contato(ctx):
    from finora.services import entity_admin
    s = ctx["s"]
    entity_admin.update(s, ctx["eid"], name="Ana", person_type="PF", document="111.444.777-35")
    entity_admin.update_details(s, ctx["eid"], address="Rua A, 10", city="Campinas", state="sp",
                                zip_code="13010050", phone="(19) 3333-4444", email="ana@x.com")
    r = receipts.build(s, ctx["add"](document_no="NF 123"))
    assert (r.party_label, r.party, r.entity_label, r.entity) == ("Pagamento para", "Maria Diarista",
                                                                  "Emitido por", "Ana")
    assert (r.signer, r.signer_doc) == ("Maria Diarista", "529.982.247-25")
    assert r.amount_words == "trezentos e cinquenta reais" and r.date_text == "11/10/2026"   # data do pagamento
    assert r.document == "NF 123" and r.reference == "Faxina de outubro" and len(r.number) == 6
    assert r.head.address_line == "Rua A, 10 — Campinas/SP — CEP 13010-050"
    assert r.head.contacts_line == "Tel: (19) 3333-4444   e-mail: ana@x.com"
    assert r.head.docs_line == "CPF 111.444.777-35"


def test_recibo_de_receita_quem_assina_e_a_entidade(ctx):
    i = ctx["add"](kind="income", description="Aula particular", amount=D("1250.40"), contact="Pedro")
    r = receipts.build(ctx["s"], i, when=date(2026, 10, 20), notes="Pago em dinheiro", entity_doc="11144477735")
    assert (r.party_label, r.party, r.entity_label) == ("Recebido de", "Pedro", "Recebido por")
    assert (r.signer, r.signer_doc) == ("Ana", "111.444.777-35")   # sem CPF na entidade: usa o informado
    assert "mil duzentos e cinquenta reais e quarenta centavos" in r.amount_words
    assert r.notes == "Pago em dinheiro" and r.date_text == "20/10/2026"


def test_sem_contato_pede_o_nome_e_aceita_completar(ctx):
    i = ctx["add"](contact="")
    with pytest.raises(ValueError, match="recebeu o pagamento"):
        receipts.build(ctx["s"], i)
    r = receipts.build(ctx["s"], i, party="João Pintor", party_doc="11222333000181")
    assert r.signer == "João Pintor" and r.signer_doc == "11.222.333/0001-81"


def test_transferencia_e_cartao_nao_tem_recibo(ctx):
    s, eid = ctx["s"], ctx["eid"]
    cash = accounts.create(s, eid, name="Carteira", kind="cash", opening_balance=D(0))
    t = entries.create(s, eid, EntryData(kind="transfer", description="Saque", amount=D("50"),
                                         due_date=date(2026, 10, 1), account_id=ctx["bank"], dest_account_id=cash))[0]
    with pytest.raises(ValueError, match="Transferências"):
        receipts.build(s, t)
    card = accounts.create(s, eid, name="Itaú", kind="card", opening_balance=D(0), closing_day=25, due_day=5)
    c = entries.create(s, eid, EntryData(kind="expense", description="Loja", amount=D("80"),
                                         due_date=date(2026, 10, 1), account_id=card))[0]
    with pytest.raises(ValueError, match="cartão"):
        receipts.build(s, c)
