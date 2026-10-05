"""Onde ficam os dados (banco, backups, preferências, licença). App portátil: tudo numa pasta só.

Regra (docs/ROADMAP.md › Distribuição):
- `data/` ao lado do programa — do executável empacotado ou, em desenvolvimento, da raiz do projeto;
- no macOS empacotado, `~/IGNF-Finora/data` (o .app não pode guardar dados dentro dele);
- se a pasta do programa não permitir gravar (ex.: "Arquivos de Programas"), `~/IGNF-Finora/data`, com aviso;
- a variável de ambiente FINORA_DATA_DIR força outra pasta (testes, uso avançado).
"""
import os
import sys
import tempfile
from pathlib import Path

HOME_FOLDER = "IGNF-Finora"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):              # executável gerado pelo PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]     # desenvolvimento: raiz do projeto


def home_data_dir() -> Path:
    return Path.home() / HOME_FOLDER / "data"


def writable(folder: Path) -> bool:
    """Cria a pasta (se preciso) e testa gravar um arquivo nela."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".teste-", delete=True):
            pass
        return True
    except OSError:
        return False


def choose_data_dir(app: Path | None = None, platform: str | None = None, frozen: bool | None = None,
                    env: dict | None = None) -> tuple[Path, str | None]:
    """(pasta de dados, aviso para o usuário ou None)."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if env.get("FINORA_DATA_DIR"):
        return Path(env["FINORA_DATA_DIR"]), None
    if platform == "darwin" and frozen:
        return home_data_dir(), None
    candidate = (app or app_dir()) / "data"
    if writable(candidate):
        return candidate, None
    fallback = home_data_dir()
    return fallback, (f"A pasta do programa ({candidate.parent}) não permite gravar dados.\n"
                      f"Seus dados vão ficar em {fallback}.\n\n"
                      f"Para manter tudo numa pasta só, copie o IGNF Finora para uma pasta sua, "
                      f"como C:\\IGNF-Finora.")


DATA_DIR, DATA_NOTICE = choose_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
