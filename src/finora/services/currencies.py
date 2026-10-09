"""Moedas além da lista do Finora (ex.: rand sul-africano): a pessoa cadastra código, símbolo e nome.

Ficam no banco (tabela currencies, valem para todas as entidades) e entram em money.CURRENCIES ao abrir,
aparecendo nas listas de moeda (contas, entidade, cotações). A cotação delas é digitada à mão.
"""
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core import money
from finora.models import Account, Currency, Entity, ExchangeRate


def load(s: Session) -> int:
    """Registra as moedas cadastradas (chamado ao abrir o app). Devolve quantas."""
    rows = list(s.scalars(select(Currency)))
    for c in rows:
        money.register(c.code, c.symbol, c.name)
    return len(rows)


def list_custom(s: Session) -> list[Currency]:
    return list(s.scalars(select(Currency).order_by(Currency.code)))


def add(s: Session, code: str, symbol: str, name: str) -> str:
    code = (code or "").strip().upper()
    symbol, name = " ".join((symbol or "").split()), " ".join((name or "").split())
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError("O código tem 3 letras (padrão ISO 4217). Ex.: ZAR para o rand sul-africano.")
    if code in money.CURRENCIES:
        raise ValueError(f"{code} já está na lista ({money.CURRENCIES[code][1]}).")
    if not symbol or len(symbol) > 6:
        raise ValueError("Informe o símbolo (até 6 caracteres). Ex.: R, ZAR.")
    if not name or len(name) > 60:
        raise ValueError("Informe o nome da moeda (até 60 letras).")
    s.add(Currency(code=code, symbol=symbol, name=name))
    s.commit()
    money.register(code, symbol, name)
    return code


def remove(s: Session, code: str) -> None:
    """Só tira se nenhuma conta, entidade ou cotação usa (para não deixar valores sem moeda)."""
    used = (s.scalar(select(func.count(Account.id)).where(Account.currency == code))
            + s.scalar(select(func.count(Entity.id)).where(Entity.currency == code))
            + s.scalar(select(func.count(ExchangeRate.id)).where(ExchangeRate.currency == code)))
    if used:
        raise ValueError(f"{code} está em uso (contas, entidades ou cotações) e não pode ser removida.")
    c = s.get(Currency, code)
    if c is not None:
        s.delete(c)
        s.commit()
    money.unregister(code)
