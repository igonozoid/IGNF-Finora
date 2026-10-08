"""Atalhos do Finora: Área de trabalho, menu Iniciar e abrir junto com o Windows (no Linux, arquivos .desktop).

O Finora é portátil (tudo numa pasta, sem instalador): os atalhos são opcionais e apontam para o programa
desta pasta. Só existem no programa empacotado (no código-fonte não há um .exe para apontar).
"""
import os
import subprocess
import sys
from pathlib import Path

NAME = "IGNF Finora"
KINDS = {"desktop": "Área de trabalho", "menu": "Menu Iniciar", "startup": "Abrir junto com o sistema"}


def exe_path() -> Path | None:
    return Path(sys.executable) if getattr(sys, "frozen", False) else None


def _desktop_dir() -> Path:
    from PySide6.QtCore import QStandardPaths
    return Path(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation))


def path_for(kind: str) -> Path:
    if sys.platform == "win32":
        programs = Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        folder = {"desktop": _desktop_dir(), "menu": programs, "startup": programs / "Startup"}[kind]
        return folder / f"{NAME}.lnk"
    home = Path.home()
    folder = {"desktop": _desktop_dir(), "menu": home / ".local" / "share" / "applications",
              "startup": home / ".config" / "autostart"}[kind]
    return folder / "ignf-finora.desktop"


def exists(kind: str) -> bool:
    return path_for(kind).exists()


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def create(kind: str, exe: Path | None = None) -> Path:
    exe = exe or exe_path()
    if exe is None:
        raise ValueError("Atalhos só podem ser criados no programa (IGNF-Finora.exe), não no código-fonte.")
    target = path_for(kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(target)});"
                  f"$s.TargetPath={_ps_quote(exe)};$s.WorkingDirectory={_ps_quote(exe.parent)};"
                  f"$s.IconLocation={_ps_quote(str(exe) + ',0')};$s.Description='Finanças pessoais';$s.Save()")
        run = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode != 0 or not target.exists():
            raise ValueError("O Windows não deixou criar o atalho." + (f" ({run.stderr.strip()[:200]})"
                                                                       if run.stderr else ""))
    else:
        target.write_text("[Desktop Entry]\nType=Application\nName=IGNF Finora\nComment=Finanças pessoais\n"
                          f"Exec=\"{exe}\"\nPath={exe.parent}\nTerminal=false\nCategories=Office;Finance;\n",
                          encoding="utf-8")
        target.chmod(0o755)
    return target


def remove(kind: str) -> None:
    p = path_for(kind)
    if p.exists():
        p.unlink()
