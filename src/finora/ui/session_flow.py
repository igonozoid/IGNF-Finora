"""Quem entra e em qual entidade: login (se precisar) e "Escolha a entidade" (se houver mais de uma)."""
from PySide6.QtWidgets import QDialog

from finora.core import current, settings
from finora.core.db import Session
from finora.core.logs import log
from finora.services import entity_admin, setup, users
from finora.services.setup import Profile
from finora.services.users import UserView
from finora.ui.session_dialogs import EntityChooser, LoginDialog


def pick_user(t: dict) -> UserView | None:
    """Pede login se há mais de um usuário ou senha; senão entra direto como o dono. None = desistiu."""
    with Session() as s:
        need = users.needs_login(s)
        owner = None if need else users.owner(s)
    if need:
        dlg = LoginDialog(t, settings.get_last_email())
        if dlg.exec() != QDialog.Accepted:
            return None
        user = dlg.user
        settings.set_last_email(user.email)
        log.info("Login: %s", user.name)
    else:
        user = owner
    if user is not None:
        current.set_user(user.id, user.name, user.is_admin)
    return user


def pick_entity(user: UserView | None, t: dict, ask: bool = False) -> Profile | None:
    """A entidade a abrir: a única, a última usada, ou a escolhida na lista (com `ask` ou sem última)."""
    with Session() as s:
        items = entity_admin.list_entities(s, user.id if user and not user.is_admin else None,
                                           include_inactive=False)
    if not items:
        return None
    last = settings.get_last_entity()
    chosen = items[0].id if len(items) == 1 else (last if last in {e.id for e in items} and not ask else None)
    if chosen is None:
        dlg = EntityChooser(items, t, last)
        if dlg.exec() != QDialog.Accepted:
            return None
        chosen = dlg.entity_id
    settings.set_last_entity(chosen)
    with Session() as s:
        return setup.current_profile(s, chosen)
