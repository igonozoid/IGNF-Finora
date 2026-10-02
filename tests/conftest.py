from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finora.models import Base
from finora.services import setup


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def profile(session):
    """Perfil pronto: 1 conta no banco com R$ 100,00 e categorias padrão."""
    return setup.run_first_setup(session, name="Ana", currency="BRL", account_name="Banco",
                                 account_kind="bank", balance=Decimal("100.00"))


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Preferências (QSettings) num espaço só dos testes: nada lê nem grava as do usuário,
    e uma licença ativada no computador não muda o resultado dos testes."""
    from finora.core import licensing, settings
    monkeypatch.setattr(settings, "ORG", "IGNF-pytest")
    monkeypatch.setattr(licensing, "_cache", None)
    settings.set_license_key("")
    yield
    settings.set_license_key("")
