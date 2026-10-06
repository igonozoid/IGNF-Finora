import os
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finora.core import db
from finora.models import Base
from finora.services import setup


# Para rodar as regras contra o banco do servidor (MariaDB/PostgreSQL), aponte para um banco de TESTE vazio:
#   FINORA_TEST_DB_URL=mysql+pymysql://usuario:senha@127.0.0.1:3306/finora_test pytest tests --ignore=tests/ui
TEST_DB_URL = os.environ.get("FINORA_TEST_DB_URL")


@pytest.fixture(scope="session")
def _server_engine():
    if not TEST_DB_URL:
        yield None
        return
    eng = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _wipe(eng):
    """Esvazia todas as tabelas entre um teste e outro (bem mais rápido que recriar)."""
    with eng.begin() as conn:
        if eng.dialect.name in ("mysql", "mariadb"):
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        if eng.dialect.name in ("mysql", "mariadb"):
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")


@pytest.fixture
def session(_server_engine):
    if _server_engine is not None:
        with Session(_server_engine) as s:
            yield s
            s.rollback()
        _wipe(_server_engine)
        return
    engine = db.sqlite_pragmas(create_engine("sqlite://"))
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def profile(session):
    """Perfil pronto: 1 conta no banco com R$ 100,00 e categorias padrão."""
    return setup.run_first_setup(session, name="Ana", currency="BRL", account_name="Banco",
                                 account_kind="bank", balance=Decimal("100.00"))


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Preferências num finora.ini só do teste: nada lê nem grava as do usuário,
    e uma licença ativada no computador não muda o resultado dos testes."""
    from finora.core import licensing, settings
    monkeypatch.setattr(settings, "FILE", tmp_path / "finora.ini")
    monkeypatch.setattr(settings, "ORG", "IGNF-pytest")   # Registro usado só pelo teste de migração
    monkeypatch.setattr(licensing, "_cache", None)
    yield


@pytest.fixture
def plus(monkeypatch):
    """Simula uma licença Plus ativada (recursos pagos liberados). Peça antes de `window`."""
    from datetime import date
    from finora.core import licensing
    from finora.core.license_key import License
    lic = License("plus", "Teste", date(2026, 1, 1), None, 1)
    monkeypatch.setattr(licensing, "current_license", lambda today=None: lic)
    monkeypatch.setattr(licensing, "stored_license", lambda: lic)
