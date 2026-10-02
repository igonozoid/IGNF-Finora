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


def get_auto_backup() -> bool:
    return _s().value("backup/auto", True, type=bool)


def set_auto_backup(on: bool) -> None:
    _s().setValue("backup/auto", on)


def get_backup_folder() -> str:
    return str(_s().value("backup/folder", ""))


def set_backup_folder(path: str) -> None:
    _s().setValue("backup/folder", path)


def get_last_backup() -> str:
    """Data/hora (ISO) do último backup manual."""
    return str(_s().value("backup/last", ""))


def set_last_backup(iso: str) -> None:
    _s().setValue("backup/last", iso)
