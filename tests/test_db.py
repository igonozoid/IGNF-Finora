from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from finora.models import Account, Entry


def test_chaves_estrangeiras_ligadas(session):
    if session.bind.dialect.name != "sqlite":
        pytest.skip("só o SQLite precisa ligar as chaves estrangeiras em cada conexão")
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_lancamento_com_conta_inexistente_e_recusado(session, profile):
    session.add(Entry(entity_id=profile.id, kind="expense", account_id=999, amount=D("10"),
                      competence_date=date(2026, 10, 1), due_date=date(2026, 10, 1), status="pending"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_nao_apaga_conta_que_tem_lancamentos(session, profile):
    acc = session.query(Account).first()
    session.add(Entry(entity_id=profile.id, kind="expense", account_id=acc.id, amount=D("10"),
                      competence_date=date(2026, 10, 1), due_date=date(2026, 10, 1), status="pending"))
    session.commit()
    session.delete(acc)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
