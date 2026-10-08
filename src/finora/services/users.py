"""Usuários: cadastro, senha e login.

Senha opcional: com um único usuário sem senha, o app abre direto (como sempre foi na Free). Basta alguém ter
senha, ou haver mais de um usuário, para o app pedir login ao abrir. Senhas guardadas com scrypt (nunca o texto).
"""
import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core.licensing import LimitError, allowed, current_edition
from finora.models import Entity, User, UserEntity

MIN_PASSWORD = 6
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_N, _R, _P = 2 ** 14, 8, 1


@dataclass(frozen=True)
class UserView:
    id: int
    name: str
    email: str
    is_admin: bool
    is_active: bool
    has_password: bool
    entities: tuple[int, ...]
    last_login: datetime | None

    @property
    def initials(self) -> str:
        words = [w for w in self.name.split() if w[:1].isalnum()]
        return "".join(w[0] for w in words[:2]).upper() or "?"


# ---------- senha ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(digest))


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres.")


# ---------- consultas ----------
def _view(s: Session, u: User) -> UserView:
    ents = tuple(s.scalars(select(UserEntity.entity_id).where(UserEntity.user_id == u.id)
                           .order_by(UserEntity.entity_id)))
    return UserView(u.id, u.name, u.email or "", u.is_admin, u.is_active, bool(u.password_hash), ents, u.last_login)


def list_users(s: Session, include_inactive: bool = True) -> list[UserView]:
    q = select(User).order_by(User.is_active.desc(), func.lower(User.name))
    if not include_inactive:
        q = q.where(User.is_active)
    return [_view(s, u) for u in s.scalars(q)]


def get(s: Session, user_id: int) -> UserView:
    return _view(s, s.get(User, user_id))


def needs_login(s: Session) -> bool:
    """Pede login se há mais de um usuário ativo ou se algum tem senha."""
    active = s.scalars(select(User).where(User.is_active)).all()
    return len(active) > 1 or any(u.password_hash for u in active)


def owner(s: Session) -> UserView | None:
    """O único usuário (quando não há login): o primeiro administrador ativo."""
    u = s.scalars(select(User).where(User.is_active, User.is_admin).order_by(User.id)).first()
    return _view(s, u) if u else None


def limit() -> int | None:
    return allowed(current_edition(), "users_max")


def active_count(s: Session) -> int:
    return s.scalar(select(func.count(User.id)).where(User.is_active))


# ---------- gravação ----------
def _check(s: Session, name: str, email: str | None, exclude_id: int | None = None) -> tuple[str, str | None]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Digite o nome do usuário.")
    email = (email or "").strip().lower() or None
    if email and not _EMAIL.match(email):
        raise ValueError("E-mail inválido. Ele é usado para entrar no app (ex.: nome@site.com).")
    if email:
        q = select(User.id).where(func.lower(User.email) == email)
        if exclude_id is not None:
            q = q.where(User.id != exclude_id)
        if s.scalar(q) is not None:
            raise ValueError("Já existe um usuário com esse e-mail.")
    return name, email


def create(s: Session, *, name: str, email: str | None = None, password: str | None = None,
           is_admin: bool = False, entity_ids: list[int] | None = None) -> int:
    lim = limit()
    if lim is not None and active_count(s) >= lim:
        raise LimitError(f"Sua edição permite até {lim} {'usuário' if lim == 1 else 'usuários'}. "
                         "Inative um usuário ou faça upgrade.")
    name, email = _check(s, name, email)
    if active_count(s) and not email:
        raise ValueError("Informe o e-mail: com mais de um usuário, cada um entra com o seu.")
    if password:
        _validate_password(password)
    u = User(name=name, email=email, password_hash=hash_password(password) if password else None,
             is_admin=is_admin, is_active=True, created=datetime.now())
    s.add(u)
    s.flush()
    for eid in entity_ids if entity_ids is not None else list(s.scalars(select(Entity.id))):
        s.add(UserEntity(user_id=u.id, entity_id=eid))
    s.commit()
    return u.id


def update(s: Session, user_id: int, *, name: str, email: str | None, is_admin: bool, is_active: bool = True) -> None:
    u = s.get(User, user_id)
    name, email = _check(s, name, email, exclude_id=user_id)
    if (u.is_admin and not is_admin) or (u.is_active and not is_active):
        _keep_an_admin(s, user_id)
    if not u.is_active and is_active:
        lim = limit()
        if lim is not None and active_count(s) >= lim:
            raise LimitError(f"Sua edição permite até {lim} usuários ativos.")
    if active_count(s) > 1 and not email:
        raise ValueError("Informe o e-mail: com mais de um usuário, cada um entra com o seu.")
    u.name, u.email, u.is_admin, u.is_active = name, email, is_admin, is_active
    s.commit()


def _keep_an_admin(s: Session, user_id: int) -> None:
    others = s.scalar(select(func.count(User.id)).where(User.is_admin, User.is_active, User.id != user_id))
    if not others:
        raise ValueError("Precisa ficar pelo menos um administrador ativo.")


def set_password(s: Session, user_id: int, password: str | None) -> None:
    """Define (ou, com None/vazio, remove) a senha. Sem senha só faz sentido com um usuário só."""
    u = s.get(User, user_id)
    if password:
        _validate_password(password)
        if not u.email:
            raise ValueError("Informe um e-mail para esse usuário antes: é com ele que se entra no app.")
        u.password_hash = hash_password(password)
    else:
        if active_count(s) > 1:
            raise ValueError("Com mais de um usuário, todos precisam de senha.")
        u.password_hash = None
    s.commit()


def set_entities(s: Session, user_id: int, entity_ids: list[int]) -> None:
    if not entity_ids:
        raise ValueError("Escolha pelo menos uma entidade para esse usuário.")
    current = set(s.scalars(select(UserEntity.entity_id).where(UserEntity.user_id == user_id)))
    for eid in current - set(entity_ids):
        s.delete(s.get(UserEntity, (user_id, eid)))
    for eid in set(entity_ids) - current:
        s.add(UserEntity(user_id=user_id, entity_id=eid))
    s.commit()


def authenticate(s: Session, email: str, password: str) -> UserView:
    """Confere e-mail e senha. Levanta ValueError com mensagem genérica (não diz qual dos dois errou)."""
    u = s.scalars(select(User).where(func.lower(User.email) == (email or "").strip().lower())).first()
    if u is None or not u.is_active or not check_password(password or "", u.password_hash):
        raise ValueError("E-mail ou senha incorretos.")
    u.last_login = datetime.now()
    s.commit()
    return _view(s, u)


def ensure_owner(s: Session, entity_id: int, name: str) -> int:
    """Primeiro uso: o dono do app vira o administrador (sem senha). Se já existe, ganha acesso à entidade."""
    u = s.scalars(select(User).where(User.is_admin).order_by(User.id)).first()
    if u is None:
        u = User(name=name.strip() or "Administrador", is_admin=True, is_active=True, created=datetime.now())
        s.add(u)
        s.flush()
    if s.get(UserEntity, (u.id, entity_id)) is None:
        s.add(UserEntity(user_id=u.id, entity_id=entity_id))
    return u.id


# ---------- PIN (um usuário só: pede só o PIN ao abrir) ----------
def pin_mode(s: Session) -> UserView | None:
    """Há um único usuário ativo, sem e-mail e com PIN? Então a abertura pede só o PIN (devolve esse usuário)."""
    active = s.scalars(select(User).where(User.is_active)).all()
    if len(active) == 1 and not active[0].email and active[0].password_hash:
        return _view(s, active[0])
    return None


def set_pin(s: Session, user_id: int, pin: str | None) -> None:
    """PIN de 4 a 8 números para abrir o app (só com um usuário). Vazio tira o PIN."""
    if active_count(s) > 1:
        raise ValueError("Com mais de um usuário, cada um entra com e-mail e senha (Administração › Usuários).")
    u = s.get(User, user_id)
    if not pin:
        u.password_hash = None
    else:
        if not (pin.isdigit() and 4 <= len(pin) <= 8):
            raise ValueError("O PIN precisa ter de 4 a 8 números.")
        u.password_hash = hash_password(pin)
    s.commit()


def authenticate_pin(s: Session, pin: str) -> UserView:
    u = pin_mode(s)
    if u is None or not check_password(pin or "", s.get(User, u.id).password_hash):
        raise ValueError("PIN incorreto.")
    s.get(User, u.id).last_login = datetime.now()
    s.commit()
    return u
