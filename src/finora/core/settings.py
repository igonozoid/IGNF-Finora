"""Preferências do usuário guardadas pelo Qt (QSettings)."""
from PySide6.QtCore import QSettings

ORG, APP = "IGNF", "Finora"


def _s() -> QSettings:
    return QSettings(ORG, APP)


def get_theme(default: str = "light") -> str:
    return str(_s().value("ui/theme", default))


def set_theme(name: str) -> None:
    _s().setValue("ui/theme", name)


def get_geometry():
    return _s().value("ui/geometry")


def set_geometry(data) -> None:
    _s().setValue("ui/geometry", data)
