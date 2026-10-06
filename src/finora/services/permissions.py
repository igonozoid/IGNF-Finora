"""Permissões por usuário, entidade e módulo (do IgnControl): Nenhum, Leitura ou Total.

Administrador tem Total em tudo. Usuário comum sem registro para um módulo usa o padrão de DEFAULTS.
"""
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from finora.core.current import current
from finora.models import (
    Account, Attachment, BankLine, Budget, Category, Contact, CostCenter, Entity, Entry, ExchangeRate, Permission,
    User, UserEntity,
)

# módulo -> (rótulo, ícone, explicação)
MODULES = {
    "financial": ("Financeiro", "fa6s.right-left",
                  "Lançamentos, contas, categorias, centros de custo, conciliação e Dashboard."),
    "contacts": ("Contatos", "fa6s.address-book", "Cadastro de pessoas e empresas."),
    "reports": ("Relatórios", "fa6s.file-lines", "DRE, fluxo de caixa, extratos, orçamento e os demais."),
    "audit": ("Auditoria", "fa6s.clock-rotate-left", "Ver o histórico de alterações."),
    "admin": ("Administração", "fa6s.shield-halved",
              "Usuários, entidades, permissões, backup, moedas, fechamento de período e licença."),
}
LEVELS = {"none": "Nenhum", "read": "Leitura", "full": "Total"}
DEFAULTS = {"financial": "full", "contacts": "full", "reports": "read", "audit": "none", "admin": "none"}
_ORDER = ["none", "read", "full"]

# telas do menu -> módulo que elas exigem
PAGE_MODULE = {"dashboard": "financial", "entries": "financial", "accounts": "financial", "categories": "financial",
               "cost_centers": "financial", "reconcile": "financial", "contacts": "contacts", "reports": "reports",
               "admin": "admin", "settings": None}


def level(s: Session, user_id: int | None, entity_id: int, module: str) -> str:
    if user_id is None:
        return "full"                       # sem login: dono do app
    u = s.get(User, user_id)
    if u is None or not u.is_active:
        return "none"
    if u.is_admin:
        return "full"
    if s.get(UserEntity, (user_id, entity_id)) is None:
        return "none"
    p = s.get(Permission, (user_id, entity_id, module))
    return p.level if p else DEFAULTS[module]


def levels(s: Session, user_id: int | None, entity_id: int) -> dict[str, str]:
    return {m: level(s, user_id, entity_id, m) for m in MODULES}


def at_least(have: str, need: str) -> bool:
    return _ORDER.index(have) >= _ORDER.index(need)


def set_level(s: Session, user_id: int, entity_id: int, module: str, value: str) -> None:
    if module not in MODULES or value not in LEVELS:
        raise ValueError("Permissão inválida.")
    u = s.get(User, user_id)
    if u.is_admin:
        raise ValueError("Administrador tem acesso total a tudo. Para limitar, tire o perfil de administrador.")
    p = s.get(Permission, (user_id, entity_id, module))
    if p is None:
        s.add(Permission(user_id=user_id, entity_id=entity_id, module=module, level=value))
    else:
        p.level = value
    s.commit()


def matrix(s: Session, user_id: int, entity_id: int) -> dict[str, str]:
    """O que está valendo para a tela de permissões (já com os padrões)."""
    return levels(s, user_id, entity_id)


def entities_for(s: Session, user_id: int | None) -> list[int]:
    if user_id is None:
        return list(s.scalars(select(Entity.id).order_by(Entity.id)))
    return list(s.scalars(select(UserEntity.entity_id).where(UserEntity.user_id == user_id)
                          .order_by(UserEntity.entity_id)))


# ---------- trava: só grava onde o usuário tem acesso Total ----------
TABLE_MODULE = {Entry: "financial", Account: "financial", Category: "financial", CostCenter: "financial",
                BankLine: "financial", Budget: "financial", Attachment: "financial", ExchangeRate: "admin",
                Contact: "contacts", Entity: "admin", User: "admin", Permission: "admin", UserEntity: "admin"}


class AccessDenied(ValueError):
    pass


def _deny_message(module: str) -> str:
    return (f"Você tem acesso só de leitura em {MODULES[module][0]} nesta entidade. "
            "Peça a um administrador para mudar sua permissão.")


@event.listens_for(Session, "before_flush")
def _guard(s: Session, _ctx, _instances) -> None:
    if not current.read_only:
        return
    for obj in list(s.new) + list(s.dirty) + list(s.deleted):
        module = TABLE_MODULE.get(type(obj))
        if module and module in current.read_only and (obj in s.new or obj in s.deleted or s.is_modified(obj)):
            if isinstance(obj, User) and obj.id == current.user_id and module == "admin":
                continue                              # trocar a própria senha/nome é permitido
            raise AccessDenied(_deny_message(module))
