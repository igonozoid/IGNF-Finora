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
    r = receipts.build(ctx["s"], ctx["add"](), city="Campinas", my_doc="111.444.777-35")
    assert (r.payer, r.payee) == ("Ana", "Maria Diarista")
    assert r.payee_doc == "529.982.247-25" and r.payer_doc == "111.444.777-35"
    assert r.body == ("Recebi de Ana, CPF 111.444.777-35 a importância de R$ 350,00 (trezentos e cinquenta reais), "
                      "referente a Faxina de outubro.")
    assert r.place_date == "Campinas, 11 de outubro de 2026"          # usa a data do pagamento
    assert len(r.number) == 6


def test_recibo_de_receita_quem_assina_e_voce(ctx):
    i = ctx["add"](kind="income", description="Aula particular", amount=D("1250.40"), contact="Pedro")
    r = receipts.build(ctx["s"], i, when=date(2026, 10, 20))
    assert (r.payer, r.payee) == ("Pedro", "Ana")
    assert "mil duzentos e cinquenta reais e quarenta centavos" in r.body
    assert r.place_date == "20 de outubro de 2026"                     # sem cidade


def test_sem_contato_pede_o_nome_e_aceita_completar(ctx):
    i = ctx["add"](contact="")
    with pytest.raises(ValueError, match="quem recebeu"):
        receipts.build(ctx["s"], i)
    r = receipts.build(ctx["s"], i, contact_name="João Pintor", contact_doc="11222333000181")
    assert r.payee == "João Pintor" and r.payee_doc == "11.222.333/0001-81"
    assert "CNPJ" not in r.body                                         # o documento do pagador é que vai no texto


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
