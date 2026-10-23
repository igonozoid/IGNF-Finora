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
DESKTOP_ID = "ignf-finora"     # Linux: nome do .desktop, do ícone e da janela (app.setDesktopFileName)


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


def icon_path() -> Path:
    """Linux: onde fica o ícone que os atalhos usam (o executável do Linux não carrega ícone, como o .exe)."""
    return Path.home() / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / f"{DESKTOP_ID}.png"


def save_icon() -> Path | None:
    """Desenha o ícone do Finora (o mesmo da janela e da bandeja) num PNG para o menu e a área de trabalho.
    Precisa do app aberto (QApplication). None se não der (o atalho sai sem ícone, como antes)."""
    try:
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QApplication
        import qtawesome as qta
        from finora.ui import theme
        if QApplication.instance() is None:
            return None
        target = icon_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        image = qta.icon("fa6s.coins", color=theme.LIGHT["acc"]).pixmap(QSize(256, 256)).toImage()
        return target if image.save(str(target)) else None
    except Exception:                                          # noqa: BLE001 — atalho sem ícone não é erro
        return None


def desktop_entry(exe: Path, icon: Path | None) -> str:
    """Conteúdo do .desktop (Linux)."""
    lines = ["[Desktop Entry]", "Type=Application", f"Name={NAME}", "Comment=Finanças pessoais",
             f'Exec="{exe}"', f"Path={exe.parent}", "Terminal=false", "Categories=Office;Finance;",
             f"StartupWMClass={exe.name}"]
    if icon is not None:
        lines.append(f"Icon={icon}")
    return "\n".join(lines) + "\n"


def refresh() -> list[str]:
    """Linux: refaz os atalhos que já existem (os criados antes da 0.6.2 saíram sem ícone). Chamado ao abrir."""
    if sys.platform == "win32" or exe_path() is None:
        return []
    done = []
    for kind in KINDS:
        if exists(kind) and f"Icon={icon_path()}" not in path_for(kind).read_text(encoding="utf-8", errors="replace"):
            create(kind)
            done.append(kind)
    return done


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
        target.write_text(desktop_entry(exe, save_icon()), encoding="utf-8")
        target.chmod(0o755)
        if kind == "desktop":                 # GNOME: sem isso o atalho na área de trabalho fica "não confiável"
            try:
                subprocess.run(["gio", "set", str(target), "metadata::trusted", "true"], capture_output=True,
                               timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
    return target


def remove(kind: str) -> None:
    p = path_for(kind)
    if p.exists():
        p.unlink()
