from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from finora.models import Account, Category
from finora.services import setup


def test_primeiro_uso_cria_tudo(session):
    assert setup.needs_setup(session)
    p = setup.run_first_setup(session, name=" Marina ", currency="BRL", account_name="Nubank",
                              account_kind="card", balance=D("250.40"))
    assert p.name == "Marina" and not setup.needs_setup(session)
    acc = session.scalars(select(Account)).one()
    assert acc.opening_balance == D("-250.40")  # cartão: fatura vira saldo negativo
    groups = session.scalar(select(func.count(Category.id)).where(Category.parent_id.is_(None)))
    assert groups == len(setup.DEFAULT_CATEGORIES)


def test_sem_categorias(session):
    setup.run_first_setup(session, name="A", currency="BRL", account_name="B", account_kind="cash",
                          balance=D(0), default_categories=False)
    assert session.scalar(select(func.count(Category.id))) == 0


def test_validacoes(session):
    with pytest.raises(ValueError):
        setup.run_first_setup(session, name=" ", currency="BRL", account_name="x", account_kind="bank", balance=D(0))
    with pytest.raises(ValueError):
        setup.run_first_setup(session, name="A", currency="XYZ", account_name="x", account_kind="bank", balance=D(0))
    assert setup.needs_setup(session)


def test_nao_roda_duas_vezes(session, profile):
    with pytest.raises(RuntimeError):
        setup.run_first_setup(session, name="B", currency="BRL", account_name="x", account_kind="bank", balance=D(0))


def test_editar_nome_do_perfil(session, profile):
    p, changed = setup.update_profile(session, profile.id, name="  Ana Paula ", currency="BRL")
    assert (p.name, p.currency, changed) == ("Ana Paula", "BRL", 0)
    assert setup.current_profile(session).name == "Ana Paula"
    with pytest.raises(ValueError):
        setup.update_profile(session, profile.id, name=" ", currency="BRL")
    with pytest.raises(ValueError):
        setup.update_profile(session, profile.id, name="Ana", currency="XYZ")


def test_trocar_moeda_na_free_leva_as_contas_junto(session, profile):
    from finora.services import accounts
    accounts.create(session, profile.id, name="Carteira", kind="cash", opening_balance=D("50"))
    p, changed = setup.update_profile(session, profile.id, name="Ana", currency="USD", accounts_too=False)
    assert p.currency == "USD" and changed == 2                  # Free: uma moeda só, ignora o "False"
    lst = accounts.list_accounts(session, profile.id)
    assert {a.currency for a in lst} == {"USD"}
    assert sum(a.balance for a in lst) == D("150.00")            # valores não são convertidos


def test_trocar_moeda_nas_edicoes_pagas_pode_manter_as_contas(session, profile, monkeypatch):
    from finora.services import accounts
    monkeypatch.setattr(accounts, "multi_currency", lambda: True)
    p, changed = setup.update_profile(session, profile.id, name="Ana", currency="EUR", accounts_too=False)
    assert p.currency == "EUR" and changed == 0
    assert accounts.list_accounts(session, profile.id)[0].currency == "BRL"
