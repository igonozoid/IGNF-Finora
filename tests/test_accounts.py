from datetime import date
from decimal import Decimal as D

import pytest

from finora.models import Entry
from finora.services import accounts


def _entry(s, entity_id, kind, account_id, amount, status="paid", dest=None):
    s.add(Entry(entity_id=entity_id, kind=kind, account_id=account_id, dest_account_id=dest, amount=D(amount),
                competence_date=date(2026, 10, 1), due_date=date(2026, 10, 1), status=status))
    s.commit()


def test_criar_e_listar(session, profile):
    acc_id = accounts.create(session, profile.id, name="Carteira", kind="cash", opening_balance=D("20"))
    lst = accounts.list_accounts(session, profile.id)
    assert [a.name for a in lst] == ["Banco", "Carteira"]
    assert next(a for a in lst if a.id == acc_id).currency == "BRL"
    assert accounts.total_balance(lst) == D("120.00")


def test_nome_repetido(session, profile):
    with pytest.raises(ValueError):
        accounts.create(session, profile.id, name=" banco ", kind="cash", opening_balance=D(0))


def test_cartao_fica_negativo(session, profile):
    acc_id = accounts.create(session, profile.id, name="Cartão", kind="card", opening_balance=D("300"))
    assert next(a for a in accounts.list_accounts(session, profile.id) if a.id == acc_id).balance == D("-300")


def test_saldo_com_lancamentos(session, profile):
    banco = accounts.list_accounts(session, profile.id)[0].id
    cart = accounts.create(session, profile.id, name="Carteira", kind="cash", opening_balance=D(0))
    _entry(session, profile.id, "income", banco, "50")
    _entry(session, profile.id, "expense", banco, "30")
    _entry(session, profile.id, "expense", banco, "999", status="pending")  # não pago: não conta
    _entry(session, profile.id, "transfer", banco, "40", dest=cart)
    saldos = {a.id: a.balance for a in accounts.list_accounts(session, profile.id)}
    assert saldos[banco] == D("80.00")  # 100 + 50 - 30 - 40
    assert saldos[cart] == D("40.00")


def test_limite_free(session, profile):
    lim = accounts.limit()
    assert lim == 3
    for i in range(lim - 1):
        accounts.create(session, profile.id, name=f"C{i}", kind="cash", opening_balance=D(0))
    assert not accounts.can_add(session, profile.id)
    with pytest.raises(accounts.LimitError):
        accounts.create(session, profile.id, name="Extra", kind="cash", opening_balance=D(0))
    # inativar libera vaga; reativar acima do limite é bloqueado
    first = accounts.list_accounts(session, profile.id)[0].id
    accounts.set_active(session, first, False)
    accounts.create(session, profile.id, name="Extra", kind="cash", opening_balance=D(0))
    with pytest.raises(accounts.LimitError):
        accounts.set_active(session, first, True)


def test_inativas_ficam_ocultas(session, profile):
    acc_id = accounts.list_accounts(session, profile.id)[0].id
    accounts.set_active(session, acc_id, False)
    assert accounts.list_accounts(session, profile.id) == []
    assert len(accounts.list_accounts(session, profile.id, include_inactive=True)) == 1


def test_outra_moeda_so_na_pro(session, profile):
    with pytest.raises(accounts.LimitError):
        accounts.create(session, profile.id, name="Wise", kind="bank", opening_balance=D(0), currency="USD")
    acc_id = accounts.create(session, profile.id, name="Wise", kind="bank", opening_balance=D(0), currency="BRL")
    with pytest.raises(accounts.LimitError):
        accounts.update(session, acc_id, name="Wise", kind="bank", opening_balance=D(0), currency="USD")
