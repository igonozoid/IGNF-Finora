"""Quem está usando o app agora (preenchido no login). A auditoria grava esse nome em cada alteração e a trava de
permissões usa `read_only` (módulos em que o usuário não tem acesso Total na entidade aberta)."""
from dataclasses import dataclass, field


@dataclass
class _Current:
    user_id: int | None = None
    user_name: str = ""
    is_admin: bool = True          # sem login (um usuário só, sem senha) = dono de tudo
    entity_id: int | None = None
    read_only: set[str] = field(default_factory=set)


current = _Current()


def set_user(user_id: int | None, name: str, is_admin: bool) -> None:
    current.user_id, current.user_name, current.is_admin = user_id, name, is_admin
    current.read_only = set()


def set_entity(entity_id: int, read_only: set[str]) -> None:
    current.entity_id, current.read_only = entity_id, set(read_only)


def clear() -> None:
    set_user(None, "", True)
    current.entity_id = None
