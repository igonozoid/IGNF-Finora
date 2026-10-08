"""Relatório de problema para o suporte: um .zip com versão, sistema e o registro de erros (finora.log).

Nada de dado financeiro: o log não guarda valores nem a chave de licença, e o banco não vai junto.
"""
import platform
import re
import zipfile
from datetime import datetime
from pathlib import Path

from finora import __version__

MAX_LOG = 2_000_000          # bytes de log por arquivo (o mais recente)
_SECRET = re.compile(r"(FNR\d-[A-Z0-9-]{10,})|(password=\S+)|(senha=\S+)", re.IGNORECASE)


def system_info(extra: dict | None = None) -> str:
    lines = [
        f"IGNF Finora {__version__}",
        f"Gerado em {datetime.now():%d/%m/%Y %H:%M}",
        f"Sistema: {platform.system()} {platform.release()} ({platform.version()}) {platform.machine()}",
        f"Python {platform.python_version()}",
    ]
    try:
        from PySide6 import __version__ as pyside
        from PySide6.QtCore import qVersion
        lines.append(f"PySide6 {pyside} · Qt {qVersion()}")
    except Exception:
        pass
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")
    return "\n".join(lines) + "\n"


def _clean(text: str) -> str:
    """Tira do log qualquer coisa que pareça chave de licença ou senha (por garantia)."""
    return _SECRET.sub("[removido]", text)


def build(dest_dir: Path, log_file: Path, description: str = "", extra: dict | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"finora-relatorio-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("sistema.txt", system_info(extra))
        if description.strip():
            z.writestr("o-que-aconteceu.txt", description.strip() + "\n")
        for f in [log_file] + [log_file.with_name(f"{log_file.name}.{i}") for i in (1, 2)]:
            if f.exists():
                data = f.read_bytes()[-MAX_LOG:]
                z.writestr(f.name, _clean(data.decode("utf-8", errors="replace")))
    return path
