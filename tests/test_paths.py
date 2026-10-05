import stat
from pathlib import Path

from PySide6.QtCore import QSettings

from finora.core import paths, settings


def test_pasta_do_programa_quando_da_para_gravar(tmp_path):
    d, notice = paths.choose_data_dir(app=tmp_path, platform="win32", frozen=True, env={})
    assert d == tmp_path / "data" and notice is None and d.is_dir()


def test_pasta_sem_permissao_vai_para_a_pasta_pessoal(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "writable", lambda folder: False)
    d, notice = paths.choose_data_dir(app=tmp_path / "Arquivos de Programas", platform="win32", frozen=True, env={})
    assert d == Path.home() / "IGNF-Finora" / "data"
    assert "não permite gravar" in notice and "C:\\IGNF-Finora" in notice


def test_mac_empacotado_usa_pasta_pessoal(tmp_path):
    d, notice = paths.choose_data_dir(app=tmp_path, platform="darwin", frozen=True, env={})
    assert d == Path.home() / "IGNF-Finora" / "data" and notice is None


def test_variavel_de_ambiente_tem_prioridade(tmp_path):
    d, _ = paths.choose_data_dir(app=tmp_path, platform="darwin", frozen=True,
                                 env={"FINORA_DATA_DIR": str(tmp_path / "x")})
    assert d == tmp_path / "x"


def test_writable_detecta_pasta_somente_leitura(tmp_path):
    assert paths.writable(tmp_path / "nova" / "sub")
    f = tmp_path / "arquivo"
    f.write_text("x")
    assert not paths.writable(f / "dentro-de-arquivo")      # caminho impossível de criar


def test_preferencias_vao_para_o_ini():
    settings.set_theme("dark")
    assert settings.FILE.exists() and "dark" in settings.FILE.read_text()


def test_migra_preferencias_do_registro():
    old = QSettings(settings.ORG, settings.APP)              # Registro "IGNF-pytest" (isolado pelo conftest)
    old.clear()
    old.setValue("ui/theme", "dark")
    old.setValue("ui/nav", "rail")
    old.sync()
    try:
        assert settings.migrate_from_registry() == 2
        assert settings.get_theme() == "dark" and settings.get_nav() == "rail"
        assert QSettings(settings.ORG, settings.APP).allKeys() == []   # Registro limpo
        assert settings.migrate_from_registry() == 0                  # só uma vez
    finally:
        QSettings(settings.ORG, settings.APP).clear()
