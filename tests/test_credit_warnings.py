"""Aviso de limite de crédito e pendência (Fase 4.5)."""
from datetime import date
from decimal import Decimal as D

from finora.services import accounts, contacts, entries
from finora.services.entries import EntryData


def _receber(s, eid, valor, pago=False):
    bank = accounts.list_accounts(s, eid)[0].id
    return entries.create(s, eid, EntryData(kind="income", description="Venda", amount=D(valor),
                                            due_date=date(2026, 10, 20), account_id=bank, contact="Maria",
                                            paid=pago, paid_date=date(2026, 10, 20) if pago else None))[0]


def test_limite_e_pendencia(session, profile):
    s, eid = session, profile.id
    contacts.create(s, eid, name="Maria", credit={"credit_limit": "1.000,00"})
    first = _receber(s, eid, "800")
    _receber(s, eid, "500", pago=True)                    # recebido não conta
    assert contacts.open_receivable(s, contacts.get_or_create(s, eid, "Maria")) == D("800.00")
    assert contacts.credit_warnings(s, eid, "maria", D("200")) == []                     # bate no limite: ok
    w = contacts.credit_warnings(s, eid, "Maria", D("300"))
    assert w == ["Maria passa do limite de crédito: R$ 800,00 em aberto + R$ 300,00 agora = R$ 1.100,00; "
                 "limite R$ 1.000,00."]
    assert contacts.credit_warnings(s, eid, "Maria", D("300"), exclude_entry_id=first) == []   # editando o 1º
    c = contacts.get_or_create(s, eid, "Maria")
    contacts.update(s, c, name="Maria", person_type="PF", document=None, roles={"customer"},
                    credit={"credit_pending": True, "credit_pending_where": "Serasa"})
    assert contacts.credit_warnings(s, eid, "Maria")[0] == "Maria tem pendência de crédito (Serasa)."


def test_sem_contato_ou_sem_limite_nao_avisa(session, profile):
    s, eid = session, profile.id
    contacts.create(s, eid, name="João")
    assert contacts.credit_warnings(s, eid, "", D("10")) == []
    assert contacts.credit_warnings(s, eid, "Ninguém", D("10")) == []
    assert contacts.credit_warnings(s, eid, "João", D("1000000")) == []
