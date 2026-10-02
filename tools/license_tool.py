"""Ferramenta do VENDEDOR para emitir chaves de licença do IGNF Finora. Não vai para o cliente.

Uso (com o .venv ativo, na pasta do projeto):
    python tools/license_tool.py init                       # cria o par de chaves (uma vez só)
    python tools/license_tool.py issue --edition plus --name "Maria Silva" [--days 365]
    python tools/license_tool.py check FNR1-XXXXX-...       # confere uma chave com a chave pública do app

A chave PRIVADA fica em %USERPROFILE%\\.ignf-finora\\license_private.pem (ou na pasta de
FINORA_LICENSE_DIR). Guarde uma cópia em lugar seguro: sem ela não dá para emitir licenças
que o app aceite, e quem a tiver consegue emitir licenças em seu nome. NUNCA a coloque no Git.
"""
import argparse
import csv
import os
import re
import secrets
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from finora.core import license_key  # noqa: E402

KEY_DIR = Path(os.environ.get("FINORA_LICENSE_DIR", Path.home() / ".ignf-finora"))
PRIVATE = KEY_DIR / "license_private.pem"
LOG = KEY_DIR / "licencas_emitidas.csv"
LICENSING_PY = ROOT / "src" / "finora" / "core" / "licensing.py"


def _load_private() -> Ed25519PrivateKey:
    if not PRIVATE.exists():
        sys.exit(f"Chave privada não encontrada em {PRIVATE}. Rode primeiro: license_tool.py init")
    return serialization.load_pem_private_key(PRIVATE.read_bytes(), password=None)


def _public_hex(priv: Ed25519PrivateKey) -> str:
    return priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def cmd_init(_args):
    if PRIVATE.exists():
        sys.exit(f"Já existe uma chave privada em {PRIVATE}. Não vou sobrescrever "
                 "(as licenças já emitidas deixariam de valer).")
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    PRIVATE.write_bytes(priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    pub = _public_hex(priv)
    src = LICENSING_PY.read_text(encoding="utf-8")
    src = re.sub(r'PUBLIC_KEY_HEX = "[0-9a-f]*"', f'PUBLIC_KEY_HEX = "{pub}"', src)
    LICENSING_PY.write_text(src, encoding="utf-8")
    print(f"Chave privada criada: {PRIVATE}")
    print(f"Chave pública gravada em {LICENSING_PY.relative_to(ROOT)}: {pub}")
    print("Faça uma cópia de segurança da chave privada AGORA (pendrive, cofre de senhas…).")


def cmd_issue(args):
    priv = _load_private()
    today = date.today()
    expires = today + timedelta(days=args.days) if args.days else None
    lic = license_key.License(args.edition, args.name, today, expires, args.id or secrets.randbits(32))
    key = license_key.encode(lic, priv)
    new_file = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        if new_file:
            w.writerow(["emitida_em", "id", "edicao", "nome", "vence", "chave"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), lic.license_id, lic.edition, lic.name,
                    expires.isoformat() if expires else "", key])
    print(key)
    print(f"\n{lic.edition.upper()} para {lic.name} · id {lic.license_id} · "
          f"{'vence em ' + expires.strftime('%d/%m/%Y') if expires else 'não vence'}  (registrada em {LOG})",
          file=sys.stderr)


def cmd_check(args):
    from finora.core.licensing import PUBLIC_KEY_HEX
    lic = license_key.decode(args.key, license_key.public_key_from_hex(PUBLIC_KEY_HEX))
    print(lic, "VENCIDA" if lic.expired() else "OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(required=True)
    sub.add_parser("init", help="cria o par de chaves").set_defaults(fn=cmd_init)
    p = sub.add_parser("issue", help="emite uma chave")
    p.add_argument("--edition", choices=["plus", "pro"], required=True)
    p.add_argument("--name", required=True, help="nome do cliente (aparece no app)")
    p.add_argument("--days", type=int, default=0, help="validade em dias (0 = não vence)")
    p.add_argument("--id", type=int, default=0, help="número da licença (padrão: aleatório)")
    p.set_defaults(fn=cmd_issue)
    p = sub.add_parser("check", help="confere uma chave")
    p.add_argument("key")
    p.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
