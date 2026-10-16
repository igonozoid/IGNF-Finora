"""Conta compartilhada entre entidades (no MCC: conta sem conta controle): aparece em todas, cada entidade lança nela
e o saldo é um só."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.models import Entry
from finora.services import accounts, entity_admin, entries, fx, reports, search
from finora.services.entries import EntryData


@pytest.fixture
def two(session, profile, plus):
    s, a = session, profile.id
    b = entity_admin.create(s, name="Padaria Sol", person_type="PJ", dre_model="personal")
    itau = accounts.create(s, a, name="Itaú compartilhada", kind="bank", opening_balance=D("1000"), shared=True)
    return dict(s=s, a=a, b=b, itau=itau)


def _pay(c, entity, kind, amount, account, **kw):
    return entries.create(c["s"], entity, EntryData(kind=kind, description=kw.pop("description", kind),
                                                    amount=D(amount), due_date=date(2026, 10, 5), account_id=account,
                                                    paid=True, paid_date=date(2026, 10, 5), **kw))[0]


def test_aparece_nas_duas_e_o_saldo_e_um_so(two):
    s, a, b, itau = two["s"], two["a"], two["b"], two["itau"]
    _pay(two, a, "expense", "200", itau)
    _pay(two, b, "income", "500", itau)                                      # a outra entidade também lança
    view_a = next(x for x in accounts.list_accounts(s, a) if x.id == itau)
    view_b = next(x for x in accounts.list_accounts(s, b) if x.id == itau)
    assert view_a.balance == view_b.balance == D("1300.00")                  # 1000 - 200 + 500
    assert view_a.shared and view_a.owner is None and view_b.owner == "Ana"
    assert [e.description for e in entries.list_entries(s, b, year=2026, month=10)] == ["income"]   # só os dela
    st = reports.account_statement(s, itau, date(2026, 10, 1), date(2026, 10, 31))
    assert st.closing == D("1300.00") and len(st.lines) == 2                 # extrato da conta: tudo
    assert [h.title for h in search.search(s, b, "itaú") if h.kind == "account"] == ["Itaú compartilhada"]


def test_transferencia_entre_conta_propria_e_compartilhada(two):
    s, b, itau = two["s"], two["b"], two["itau"]
    caixa_b = accounts.list_accounts(s, b)[0].id
    _pay(two, b, "transfer", "100", caixa_b, dest_account_id=itau)
    bal = {x.id: x.balance for x in accounts.list_accounts(s, b)}
    assert bal[itau] == D("1100.00") and bal[caixa_b] == D("-100.00")


def test_conta_nao_compartilhada_continua_so_da_dona(two):
    s, a, b = two["s"], two["a"], two["b"]
    bank_a = next(x.id for x in accounts.list_accounts(s, a) if not x.shared)
    assert bank_a not in [x.id for x in accounts.list_accounts(s, b)]
    with pytest.raises(ValueError, match="Escolha a conta"):
        _pay(two, b, "expense", "10", bank_a)


def test_regras_de_nome_cartao_e_descompartilhar(two):
    s, a, b, itau = two["s"], two["a"], two["b"], two["itau"]
    with pytest.raises(ValueError, match="Já existe"):
        accounts.create(s, b, name="itaú COMPARTILHADA", kind="cash", opening_balance=D(0))   # já visível em B
    accounts.create(s, b, name="Caixa da padaria", kind="cash", opening_balance=D(0))
    with pytest.raises(ValueError, match="em outra entidade"):
        accounts.create(s, a, name="Caixa da padaria", kind="cash", opening_balance=D(0), shared=True)
    with pytest.raises(ValueError, match="Cartão de crédito não pode"):
        accounts.create(s, a, name="Visa", kind="card", opening_balance=D(0), shared=True)
    accounts.update(s, itau, name="Itaú", kind="bank", opening_balance=D("1000"), shared=False)   # ninguém usou
    assert itau not in [x.id for x in accounts.list_accounts(s, b)]
    accounts.update(s, itau, name="Itaú", kind="bank", opening_balance=D("1000"), shared=True)
    _pay(two, b, "expense", "50", itau)
    with pytest.raises(ValueError, match="continuar compartilhada"):
        accounts.update(s, itau, name="Itaú", kind="bank", opening_balance=D("1000"), shared=False)
    accounts.update(s, itau, name="Itaú (empresa)", kind="bank", opening_balance=D("1000"))   # None mantém
    assert next(x for x in accounts.list_accounts(s, b) if x.id == itau).shared


def test_valor_na_moeda_principal_pela_entidade_do_lancamento(session, profile, plus):
    s, a = session, profile.id
    b = entity_admin.create(s, name="Filial EUA", person_type="PJ", currency="USD", dre_model="personal")
    itau = accounts.create(s, a, name="Conta global", kind="bank", opening_balance=D(0), shared=True)
    fx.set_rate(s, b, "BRL", date(2026, 10, 1), D("0.20"))                  # na filial, 1 BRL = 0,20 USD
    i = _pay(dict(s=s), b, "expense", "100", itau)
    assert s.get(Entry, i).base_amount == D("20.00")                         # convertido para USD (da filial)
