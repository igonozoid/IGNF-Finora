"""Gera o pacote portátil do IGNF Finora para o sistema atual (Windows ou Linux).

    python tools/build.py

Resultado em dist/: a pasta IGNF-Finora (programa) e IGNF-Finora-<versão>-<sistema>.zip (Windows) ou .tar.gz
(Linux). Antes de compactar, roda o executável com --teste numa pasta de dados vazia: se algo faltar no pacote
(fontes, tradução, migrações, telas), o build falha.
"""
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from finora import __version__  # noqa: E402

DIST = ROOT / "dist"
PKG = DIST / "IGNF-Finora"
SYSTEM = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform, sys.platform)


def make_icon() -> None:
    """Ícone do programa a partir do mesmo desenho do app (moedas, cor de destaque)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication
    import qtawesome as qta
    app = QApplication.instance() or QApplication([])
    from finora.ui import theme
    icon = qta.icon("fa6s.coins", color=theme.LIGHT["acc"])
    out = ROOT / "packaging"
    if sys.platform == "win32":
        icon.pixmap(QSize(256, 256)).toImage().save(str(out / "finora.ico"))
    icon.pixmap(QSize(256, 256)).toImage().save(str(out / "finora.png"))
    del app


def pyinstaller() -> None:
    shutil.rmtree(PKG, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
                    "--workpath", str(ROOT / "build"), str(ROOT / "packaging" / "finora.spec")], check=True)
    shutil.copy(ROOT / "packaging" / "LEIA-ME.txt", PKG / "LEIA-ME.txt")


def smoke_test() -> None:
    exe = PKG / ("IGNF-Finora.exe" if sys.platform == "win32" else "IGNF-Finora")
    with tempfile.TemporaryDirectory() as data:
        env = dict(os.environ, FINORA_DATA_DIR=data, QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([str(exe), "--teste"], env=env, timeout=180)
        if r.returncode != 0:
            sys.exit(f"O executável falhou no teste (código {r.returncode}). Veja {data}.")
    if (PKG / "data").exists():                  # o teste usa outra pasta; o pacote sai sem dados
        shutil.rmtree(PKG / "data")
    print("Teste do executável: OK")


def archive() -> Path:
    name = f"IGNF-Finora-{__version__}-{SYSTEM}"
    if sys.platform == "win32":
        out = DIST / f"{name}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for f in PKG.rglob("*"):
                z.write(f, Path("IGNF-Finora") / f.relative_to(PKG))
    else:
        out = DIST / f"{name}.tar.gz"
        with tarfile.open(out, "w:gz") as t:
            t.add(PKG, arcname="IGNF-Finora")
    return out


def sign() -> None:
    """Assina o .exe (Windows) se houver certificado: FINORA_SIGN_PFX (arquivo .pfx) e FINORA_SIGN_PASS (senha).
    Sem certificado, segue sem assinar (o Windows mostra "editor desconhecido"). Ver docs/ASSINATURA.md."""
    pfx, pwd = os.environ.get("FINORA_SIGN_PFX"), os.environ.get("FINORA_SIGN_PASS", "")
    if sys.platform != "win32" or not pfx:
        print("Sem certificado (FINORA_SIGN_PFX): o executável sai sem assinatura.")
        return
    tool = shutil.which("signtool") or next((str(p) for p in Path("C:/Program Files (x86)/Windows Kits/10/bin")
                                             .glob("*/x64/signtool.exe")), None)
    if not tool:
        sys.exit("signtool não encontrado (instale o Windows SDK).")
    exe = PKG / "IGNF-Finora.exe"
    r = subprocess.run([tool, "sign", "/f", pfx, "/p", pwd, "/fd", "sha256", "/tr", "http://timestamp.digicert.com",
                        "/td", "sha256", "/d", "IGNF Finora", str(exe)])
    if r.returncode != 0:
        sys.exit("A assinatura falhou.")
    print(f"Assinado: {exe.name}")


def size(path: Path) -> str:
    total = path.stat().st_size if path.is_file() else sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return f"{total / 1024 / 1024:.0f} MB"


if __name__ == "__main__":
    make_icon()
    pyinstaller()
    sign()
    smoke_test()
    out = archive()
    print(f"Pasta: {PKG} ({size(PKG)})\nPacote: {out} ({size(out)})")
