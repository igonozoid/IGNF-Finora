"""Preferências do usuário, num arquivo dentro da pasta de dados (data/finora.ini): app portátil,
nada no Registro do Windows."""
from dataclasses import dataclass
from urllib.parse import quote

from PySide6.QtCore import QSettings

from finora.core.paths import DATA_DIR

ORG, APP = "IGNF", "Finora"
FILE = DATA_DIR / "finora.ini"


def _s() -> QSettings:
    return QSettings(str(FILE), QSettings.IniFormat)


def migrate_from_registry() -> int:
    """Versões antigas guardavam as preferências no Registro (QSettings nativo). Copia para o finora.ini
    na primeira vez e limpa o Registro. Retorna quantas preferências foram trazidas."""
    if FILE.exists():
        return 0
    old = QSettings(ORG, APP)
    keys = old.allKeys()
    if not keys:
        return 0
    new = _s()
    for k in keys:
        new.setValue(k, old.value(k))
    new.sync()
    old.clear()
    return len(keys)


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


def get_cloud_folder() -> str:
    """Pasta sincronizada com a nuvem (OneDrive, Google Drive, Dropbox…) para o backup ao fechar. Vazio = desligado."""
    return str(_s().value("backup/cloud", ""))


def set_cloud_folder(path: str) -> None:
    _s().setValue("backup/cloud", path)


def get_last_entity() -> int | None:
    v = _s().value("session/entity", 0, type=int)
    return v or None


def set_last_entity(entity_id: int) -> None:
    _s().setValue("session/entity", entity_id)


def get_last_email() -> str:
    return str(_s().value("session/email", ""))


def set_last_email(email: str) -> None:
    _s().setValue("session/email", email)


def get_last_backup() -> str:
    """Data/hora (ISO) do último backup manual."""
    return str(_s().value("backup/last", ""))


def set_last_backup(iso: str) -> None:
    _s().setValue("backup/last", iso)


NAV_MODES = {"sidebar": "Barra lateral", "rail": "Só ícones", "tabs": "Abas no topo"}


def get_nav() -> str:
    mode = str(_s().value("ui/nav", "sidebar"))
    return mode if mode in NAV_MODES else "sidebar"


def set_nav(mode: str) -> None:
    _s().setValue("ui/nav", mode)


def get_license_key() -> str:
    return str(_s().value("license/key", ""))


def set_license_key(key: str) -> None:
    _s().setValue("license/key", key)


def get_receipt_defaults() -> tuple[str, str]:
    """(cidade, seu CPF/CNPJ) usados no último recibo."""
    s = _s()
    return str(s.value("receipt/city", "")), str(s.value("receipt/my_doc", ""))


def set_receipt_defaults(city: str, my_doc: str) -> None:
    s = _s()
    s.setValue("receipt/city", city)
    s.setValue("receipt/my_doc", my_doc)


# ---------- onde ficam os dados (este PC ou servidor na rede) ----------
DB_MODES = {"local": "Neste computador", "client": "Num servidor da rede", "server": "Este computador é o servidor"}


@dataclass
class DbConfig:
    mode: str = "local"           # local | client | server
    host: str = ""
    port: int = 3306
    name: str = "finora"
    user: str = "finora"
    password: str = ""

    def url(self) -> str:
        """Endereço do banco para o SQLAlchemy (só nos modos com servidor)."""
        host = "127.0.0.1" if self.mode == "server" else self.host
        user, password = quote(self.user, safe=""), quote(self.password, safe="")
        return f"mysql+pymysql://{user}:{password}@{host}:{self.port}/{self.name}?charset=utf8mb4"


def get_db_config() -> DbConfig:
    from finora.core import secret
    s = _s()
    return DbConfig(str(s.value("db/mode", "local")), str(s.value("db/host", "")), s.value("db/port", 3306, type=int),
                    str(s.value("db/name", "finora")), str(s.value("db/user", "finora")),
                    secret.unprotect(str(s.value("db/password", ""))))


def set_db_config(cfg: DbConfig) -> None:
    from finora.core import secret
    s = _s()
    s.setValue("db/mode", cfg.mode)
    s.setValue("db/host", cfg.host)
    s.setValue("db/port", cfg.port)
    s.setValue("db/name", cfg.name)
    s.setValue("db/user", cfg.user)
    s.setValue("db/password", secret.protect(cfg.password))
