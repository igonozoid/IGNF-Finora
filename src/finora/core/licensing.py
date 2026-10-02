"""Edições (Free/Plus/Pro), recursos de cada uma e a licença ativada neste computador."""
from datetime import date
from enum import Enum

from finora.core import license_key


class Edition(str, Enum):
    FREE = "free"
    PLUS = "plus"
    PRO = "pro"


FEATURES = {
    Edition.FREE: {"accounts_max": 3, "ofx": False, "attachments": False, "budget": False, "export": False, "cloud_backup": False, "doc_lookup": False, "multi_currency": False, "entities_max": 1},
    Edition.PLUS: {"accounts_max": None, "ofx": True, "attachments": True, "budget": True, "export": True, "cloud_backup": True, "doc_lookup": False, "multi_currency": False, "entities_max": 1},
    Edition.PRO:  {"accounts_max": None, "ofx": True, "attachments": True, "budget": True, "export": True, "cloud_backup": True, "doc_lookup": True, "multi_currency": True, "entities_max": None},
}

# Chave pública que confere as licenças. Gerada por tools/license_tool.py init (a privada fica fora do Git).
PUBLIC_KEY_HEX = "8ec33495f00e6a483ed629a16160ecc42334e98fafb505563df41fe2d716dd47"

_cache: tuple[str, license_key.License | None] | None = None   # (chave guardada, licença lida)


def _public_key():
    if not PUBLIC_KEY_HEX:
        raise license_key.LicenseError("Este app ainda não aceita licenças (chave pública ausente).")
    return license_key.public_key_from_hex(PUBLIC_KEY_HEX)


def _stored_key() -> str:
    from finora.core import settings
    return settings.get_license_key()


def current_license(today: date | None = None) -> license_key.License | None:
    """A licença ativada e ainda válida, ou None (= edição Free)."""
    global _cache
    key = _stored_key()
    if _cache is None or _cache[0] != key:
        try:
            lic = license_key.decode(key, _public_key()) if key else None
        except license_key.LicenseError:
            lic = None
        _cache = (key, lic)
    lic = _cache[1]
    return None if lic is None or lic.expired(today) else lic


def stored_license() -> license_key.License | None:
    """A licença guardada, mesmo vencida (para mostrar "venceu em …")."""
    current_license()
    return _cache[1] if _cache else None


def current_edition() -> Edition:
    lic = current_license()
    return Edition(lic.edition) if lic else Edition.FREE


def activate(key: str, today: date | None = None) -> license_key.License:
    """Confere e guarda a chave. Levanta LicenseError com uma mensagem pronta para o usuário."""
    lic = license_key.decode(key, _public_key())
    if lic.expired(today):
        raise license_key.LicenseError(f"Essa licença venceu em {lic.expires:%d/%m/%Y}.")
    from finora.core import settings
    settings.set_license_key(key.strip())
    return lic


def deactivate() -> None:
    from finora.core import settings
    settings.set_license_key("")


def allowed(edition: Edition, feature: str):
    return FEATURES[edition].get(feature)
