from datetime import date

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from finora.core import license_key, licensing
from finora.core.license_key import License, LicenseError
from finora.core.licensing import Edition


@pytest.fixture
def keys(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", pub)
    return priv


def _key(priv, edition="plus", name="Maria Silva", expires=None, lic_id=42):
    return license_key.encode(License(edition, name, date(2026, 10, 2), expires, lic_id), priv)


def test_ida_e_volta(keys):
    k = _key(keys, "pro", "José Ação Ltda", date(2027, 10, 2))
    assert k.startswith("FNR1-") and all(len(g) <= 5 for g in k.split("-")[1:])
    lic = license_key.decode(k, keys.public_key())
    assert (lic.edition, lic.name, lic.issued, lic.expires, lic.license_id) == \
        ("pro", "José Ação Ltda", date(2026, 10, 2), date(2027, 10, 2), 42)


def test_tolera_espacos_quebras_e_minusculas(keys):
    k = _key(keys)
    messy = "  " + k.lower()[:40] + "\n  " + k.lower()[40:].replace("-", " - ") + " "
    assert license_key.decode(messy, keys.public_key()).name == "Maria Silva"


@pytest.mark.parametrize("mexer", [
    lambda k: k[:-1] + ("A" if k[-1] != "A" else "B"),       # assinatura alterada
    lambda k: k[:12] + ("A" if k[12] != "A" else "B") + k[13:],  # dados alterados (ex.: trocar edição)
    lambda k: k[:30],                                          # incompleta
    lambda k: "ABC-123",                                       # outro produto
    lambda k: k.replace(k[10], "1"),                           # caractere fora do Base32
])
def test_chave_adulterada_e_recusada(keys, mexer):
    with pytest.raises(LicenseError):
        license_key.decode(mexer(_key(keys)), keys.public_key())


def test_chave_de_outro_emissor_e_recusada(keys):
    other = Ed25519PrivateKey.generate()
    with pytest.raises(LicenseError, match="inválida"):
        license_key.decode(_key(other), keys.public_key())


def test_ativar_muda_a_edicao_e_os_recursos(keys):
    assert licensing.current_edition() is Edition.FREE
    assert licensing.allowed(licensing.current_edition(), "accounts_max") == 3
    lic = licensing.activate(_key(keys, "plus"))
    assert lic.edition == "plus" and licensing.current_edition() is Edition.PLUS
    assert licensing.allowed(licensing.current_edition(), "accounts_max") is None
    assert licensing.current_license().name == "Maria Silva"
    licensing.deactivate()
    assert licensing.current_edition() is Edition.FREE


def test_licenca_vencida(keys):
    k = _key(keys, expires=date(2026, 12, 31))
    with pytest.raises(LicenseError, match="venceu em 31/12/2026"):
        licensing.activate(k, today=date(2027, 1, 1))
    licensing.activate(k, today=date(2026, 12, 31))       # último dia ainda vale
    assert licensing.current_license(today=date(2026, 12, 31)) is not None
    assert licensing.current_license(today=date(2027, 1, 1)) is None   # vencida -> Free
    assert licensing.stored_license().expires == date(2026, 12, 31)


def test_chave_ruim_guardada_vira_free(keys):
    from finora.core import settings
    settings.set_license_key("FNR1-LIXO")
    assert licensing.current_edition() is Edition.FREE


def test_sem_chave_publica_nao_ativa(monkeypatch):
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", "")
    with pytest.raises(LicenseError, match="não aceita licenças"):
        licensing.activate("FNR1-AAAAA")
