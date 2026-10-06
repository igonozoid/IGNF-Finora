"""Primeiro uso: cria o perfil (entidade), a 1ª conta e as categorias padrão."""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finora.core.money import CURRENCIES
from finora.models import Account, Category, Entity
from finora.services.accounts import KINDS

ACCOUNT_KINDS = KINDS

# (dre_group, tipo, nome do grupo, [subcategorias])
DEFAULT_CATEGORIES = [
    ("receitas", "income", "Receitas", ["Salário", "Renda extra", "Rendimentos", "Outras receitas"]),
    ("moradia", "expense", "Moradia", ["Aluguel ou financiamento", "Condomínio", "Luz", "Água", "Gás",
                                       "Internet e telefone", "IPTU", "Manutenção da casa"]),
    ("alimentacao", "expense", "Alimentação", ["Supermercado", "Feira e padaria", "Restaurantes e delivery"]),
    ("transporte", "expense", "Transporte", ["Combustível", "Ônibus, metrô e apps", "Manutenção do veículo",
                                             "IPVA e seguro"]),
    ("saude", "expense", "Saúde", ["Plano de saúde", "Farmácia", "Consultas e exames", "Academia"]),
    ("educacao", "expense", "Educação", ["Escola ou faculdade", "Cursos", "Livros e material"]),
    ("lazer", "expense", "Lazer", ["Viagens", "Passeios e eventos", "Assinaturas (streaming)", "Hobbies"]),
    ("outras", "expense", "Outras despesas", ["Roupas", "Cuidados pessoais", "Presentes", "Tarifas bancárias",
                                              "Impostos e taxas", "Outros"]),
    ("investimentos", "expense", "Investimentos/Reserva", ["Reserva de emergência", "Investimentos",
                                                           "Previdência"]),
]


@dataclass(frozen=True)
class Profile:
    id: int
    name: str
    currency: str


def needs_setup(s: Session) -> bool:
    return s.scalar(select(Entity.id).limit(1)) is None


def current_profile(s: Session) -> Profile | None:
    e = s.scalars(select(Entity).order_by(Entity.id).limit(1)).first()
    return Profile(e.id, e.name, e.currency) if e else None


def update_profile(s: Session, entity_id: int, *, name: str, currency: str,
                   accounts_too: bool = True) -> tuple[Profile, int]:
    """Muda nome e/ou moeda principal. Os VALORES não são convertidos (não há câmbio): só a moeda exibida.

    Ao trocar a moeda, as contas que usavam a moeda antiga passam para a nova. Na Free isso é
    obrigatório (uma moeda só); nas edições pagas, com `accounts_too=False`, elas ficam como estão.
    Retorna (perfil atualizado, quantas contas mudaram de moeda).
    """
    from finora.services.accounts import multi_currency
    name = name.strip()
    if not name:
        raise ValueError("Digite seu nome (ou apelido).")
    if currency not in CURRENCIES:
        raise ValueError(f"Moeda não suportada: {currency}")
    e = s.get(Entity, entity_id)
    changed = 0
    try:
        if currency != e.currency and (accounts_too or not multi_currency()):
            for a in s.scalars(select(Account).where(Account.entity_id == entity_id,
                                                     Account.currency == e.currency)):
                a.currency = currency
                changed += 1
        e.name, e.currency = name, currency
        s.commit()
    except Exception:
        s.rollback()
        raise
    return Profile(e.id, e.name, e.currency), changed


def run_first_setup(s: Session, *, name: str, currency: str, account_name: str, account_kind: str,
                    balance: Decimal, default_categories: bool = True) -> Profile:
    """Grava tudo numa transação só. Para cartão, `balance` é a fatura em aberto (vira saldo negativo)."""
    name, account_name = name.strip(), account_name.strip()
    if not name:
        raise ValueError("Informe seu nome.")
    if not account_name:
        raise ValueError("Dê um nome para a conta.")
    if currency not in CURRENCIES:
        raise ValueError(f"Moeda não suportada: {currency}")
    if account_kind not in ACCOUNT_KINDS:
        raise ValueError(f"Tipo de conta inválido: {account_kind}")
    if not needs_setup(s):
        raise RuntimeError("O primeiro uso já foi concluído.")
    if account_kind == "card":
        balance = -abs(balance)

    try:
        e = Entity(name=name, currency=currency)
        s.add(e)
        s.flush()
        s.add(Account(entity_id=e.id, name=account_name, kind=account_kind, currency=currency,
                      opening_balance=balance, is_active=True))
        if default_categories:
            _add_default_categories(s, e.id)
        profile = Profile(e.id, e.name, e.currency)
        s.commit()
    except Exception:
        s.rollback()
        raise
    return profile


def _add_default_categories(s: Session, entity_id: int) -> None:
    for gi, (group, kind, gname, children) in enumerate(DEFAULT_CATEGORIES, start=1):
        parent = Category(entity_id=entity_id, code=str(gi), name=gname, kind=kind, dre_group=group,
                          is_active=True)
        s.add(parent)
        s.flush()
        for ci, child in enumerate(children, start=1):
            s.add(Category(entity_id=entity_id, parent_id=parent.id, code=f"{gi}.{ci}", name=child,
                           kind=kind, dre_group=group, is_active=True))
