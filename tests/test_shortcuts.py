import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")      # o ícone é desenhado com o Qt, sem precisar de tela

from finora.core import shortcuts


def test_atalho_cria_e_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: tmp_path / "Desktop")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(shortcuts.Path, "home", staticmethod(lambda: tmp_path))
    with pytest.raises(ValueError, match="código-fonte"):
        shortcuts.create("desktop")                       # rodando pelo código: não há .exe
    exe = tmp_path / "IGNF-Finora" / "IGNF-Finora.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    for kind in shortcuts.KINDS:
        target = shortcuts.create(kind, exe)
        assert target.exists() and shortcuts.exists(kind) and str(tmp_path) in str(target)
        if sys.platform != "win32":
            assert str(exe) in target.read_text()
        shortcuts.remove(kind)
        assert not shortcuts.exists(kind)


def test_atalho_do_linux_tem_icone(tmp_path, monkeypatch, qapp):
    """O executável do Linux não carrega ícone: o .desktop aponta para um PNG que o Finora desenha (o da janela)."""
    monkeypatch.setattr(shortcuts.Path, "home", staticmethod(lambda: tmp_path))
    icon = shortcuts.save_icon()
    assert icon == shortcuts.icon_path() and icon.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    exe = tmp_path / "IGNF-Finora" / "IGNF-Finora"
    text = shortcuts.desktop_entry(exe, icon)
    assert f"Icon={icon}" in text and f'Exec="{exe}"' in text and "StartupWMClass=IGNF-Finora" in text
    assert "Icon=" not in shortcuts.desktop_entry(exe, None)           # sem ícone: como antes, sem quebrar


def test_atalho_antigo_sem_icone_e_refeito(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(shortcuts.sys, "platform", "linux")
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: tmp_path / "Desktop")
    monkeypatch.setattr(shortcuts.Path, "home", staticmethod(lambda: tmp_path))
    exe = tmp_path / "IGNF-Finora" / "IGNF-Finora"
    exe.parent.mkdir()
    exe.write_bytes(b"\x7fELF")
    monkeypatch.setattr(shortcuts, "exe_path", lambda: exe)
    menu = shortcuts.path_for("menu")
    menu.parent.mkdir(parents=True)
    menu.write_text("[Desktop Entry]\nType=Application\nName=IGNF Finora\nExec=x\n", encoding="utf-8")   # 0.6.1
    assert shortcuts.refresh() == ["menu"]                             # só o que existia
    assert f"Icon={shortcuts.icon_path()}" in menu.read_text(encoding="utf-8")
    assert not shortcuts.exists("desktop") and shortcuts.refresh() == []   # já com ícone: não mexe de novo
