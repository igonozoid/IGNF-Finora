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
