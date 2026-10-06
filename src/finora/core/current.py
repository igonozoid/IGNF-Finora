"""Quem está usando o app agora (preenchido no login). A auditoria grava esse nome em cada alteração."""
from dataclasses import dataclass


@dataclass
class _Current:
    user_id: int | None = None
    user_name: str = ""
    is_admin: bool = True          # sem login (um usuário só, sem senha) = dono de tudo


current = _Current()


def set_user(user_id: int | None, name: str, is_admin: bool) -> None:
    current.user_id, current.user_name, current.is_admin = user_id, name, is_admin


def clear() -> None:
    set_user(None, "", True)
