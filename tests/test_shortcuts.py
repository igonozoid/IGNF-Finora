import sys

import pytest

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
