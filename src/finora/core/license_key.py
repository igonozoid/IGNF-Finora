"""Chave de licença offline, assinada com Ed25519.

Formato: FNR1-XXXXX-XXXXX-… (Base32 de payload + assinatura de 64 bytes).
Payload (big-endian):
    versão u8 | edição u8 (1=plus, 2=pro) | emitida u16 | vence u16 (0 = nunca) | id u32 | tamanho do nome u8 | nome UTF-8
Datas em dias desde 01/01/2024.

O app só tem a chave PÚBLICA (confere a assinatura). A chave PRIVADA, que emite licenças,
fica fora do repositório — ver tools/license_tool.py.
"""
import base64
import struct
from dataclasses import dataclass
from datetime import date, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PREFIX = "FNR1"
VERSION = 1
EPOCH = date(2024, 1, 1)
EDITION_CODES = {1: "plus", 2: "pro"}
SIG_LEN = 64
MAX_NAME = 60


class LicenseError(ValueError):
    """Chave inválida, de outro produto ou vencida (mensagem já pronta para o usuário)."""


@dataclass(frozen=True)
class License:
    edition: str            # "plus" | "pro"
    name: str               # para quem foi emitida
    issued: date
    expires: date | None    # None = não vence
    license_id: int

    def expired(self, today: date | None = None) -> bool:
        return self.expires is not None and (today or date.today()) > self.expires


def _days(d: date | None) -> int:
    return 0 if d is None else (d - EPOCH).days


def _date(n: int) -> date | None:
    return None if n == 0 else EPOCH + timedelta(days=n)


def _payload(lic: License) -> bytes:
    code = {v: k for k, v in EDITION_CODES.items()}[lic.edition]
    name = lic.name.strip().encode("utf-8")[:MAX_NAME * 4]
    return struct.pack(">BBHHIB", VERSION, code, _days(lic.issued), _days(lic.expires), lic.license_id,
                       len(name)) + name


def encode(lic: License, private_key: Ed25519PrivateKey) -> str:
    """Gera a chave para o cliente (usado só pela ferramenta de emissão)."""
    data = _payload(lic)
    raw = data + private_key.sign(data)
    b32 = base64.b32encode(raw).decode().rstrip("=")
    return PREFIX + "-" + "-".join(b32[i:i + 5] for i in range(0, len(b32), 5))


def decode(key: str, public_key: Ed25519PublicKey) -> License:
    """Confere a assinatura e lê a licença. Não olha a validade (ver License.expired)."""
    text = "".join(key.split()).replace("-", "").upper()
    if not text.startswith(PREFIX):
        raise LicenseError("Isso não parece uma chave do IGNF Finora. Ela começa com FNR1-.")
    b32 = text[len(PREFIX):]
    try:
        raw = base64.b32decode(b32 + "=" * (-len(b32) % 8))
    except (ValueError, base64.binascii.Error):
        raise LicenseError("A chave tem caracteres inválidos. Copie e cole de novo, sem alterar nada.")
    if len(raw) < 12 + SIG_LEN:
        raise LicenseError("A chave está incompleta. Copie e cole de novo, por inteiro.")
    data, sig = raw[:-SIG_LEN], raw[-SIG_LEN:]
    try:
        public_key.verify(sig, data)
    except InvalidSignature:
        raise LicenseError("Chave inválida. Confira se copiou a chave inteira, sem alterar nada.")
    version, code, issued, expires, lic_id, n = struct.unpack(">BBHHIB", data[:11])
    if version != VERSION or code not in EDITION_CODES:
        raise LicenseError("Essa chave é de uma versão mais nova do IGNF Finora. Atualize o app.")
    return License(EDITION_CODES[code], data[11:11 + n].decode("utf-8"), _date(issued), _date(expires), lic_id)


def public_key_from_hex(hex_key: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_key))
