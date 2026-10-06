from finora.core import settings
from finora.server import mariadb
from finora.services import dbcopy
from finora.ui import data_location_section as dls


def _section(window):
    window.go_to("settings")
    return window.page("settings").data_location


def test_conectar_num_servidor_da_rede(plus, window, dialogs, monkeypatch):
    sec = _section(window)
    calls = []
    monkeypatch.setattr(mariadb, "check_connection", lambda h, p, pw: calls.append((h, p, pw)))
    monkeypatch.setattr(dbcopy, "has_data", lambda eng: eng.dialect.name == "sqlite")   # servidor vazio
    monkeypatch.setattr(dbcopy, "copy_all", lambda src, dst: calls.append("copiou"))
    restarted = []
    sec.restart_requested.connect(lambda: restarted.append(1))
    sec.mode_group.button(1).click()
    sec.connect_btn.click()
    assert "Informe o endereço" in sec.client_status.text()
    sec.host.setText("192.168.0.10")
    sec.password.setText("abcd-efgh-jkmn")
    sec.connect_btn.click()                                   # dialogs responde "Sim" para levar os dados
    assert calls[0] == ("192.168.0.10", 3306, "abcd-efgh-jkmn") and "copiou" in calls
    cfg = settings.get_db_config()
    assert (cfg.mode, cfg.host, cfg.password) == ("client", "192.168.0.10", "abcd-efgh-jkmn") and restarted


def test_servidor_recusa_senha(plus, window, monkeypatch):
    sec = _section(window)

    def refuse(*a):
        raise mariadb.ServerError("O servidor respondeu, mas recusou a senha.")

    monkeypatch.setattr(mariadb, "check_connection", refuse)
    sec.mode_group.button(1).click()
    sec.host.setText("10.0.0.5")
    sec.test_btn.click()
    assert "recusou a senha" in sec.client_status.text() and settings.get_db_config().mode == "local"


def test_tornar_este_computador_o_servidor(plus, window, dialogs, monkeypatch):
    sec = _section(window)
    steps = []
    monkeypatch.setattr(mariadb, "installed", lambda lay=None: True)
    monkeypatch.setattr(mariadb, "initialize", lambda lay, root, port: steps.append(("init", port)))
    monkeypatch.setattr(mariadb, "start", lambda lay, port: steps.append("start"))
    monkeypatch.setattr(mariadb, "wait_ready", lambda *a, **k: None)
    monkeypatch.setattr(mariadb, "setup_database", lambda port, root, pw: steps.append(("setup", pw)))
    monkeypatch.setattr(mariadb, "lan_addresses", lambda: ["10.0.0.103"])
    monkeypatch.setattr(dbcopy, "has_data", lambda eng: False)
    monkeypatch.setattr(dbcopy, "copy_all", lambda src, dst: steps.append("copiou"))
    sec.mode_group.button(2).click()
    sec.refresh()
    assert sec.start_btn.text() == "Tornar este computador o servidor" and sec.take_data.isVisible()
    sec.start_btn.click()
    cfg = settings.get_db_config()
    assert cfg.mode == "server" and cfg.port == 3306 and len(cfg.password) == 14
    assert steps[:2] == [("init", 3306), "start"] and ("setup", cfg.password) in steps and "copiou" in steps
    assert settings.get_server_root()                         # senha do administrador do banco guardada
    monkeypatch.setattr(mariadb, "is_listening", lambda port, host="127.0.0.1": True)
    sec.refresh()
    assert "10.0.0.103" in sec.info_text.text() and cfg.password in sec.info_text.text()


def test_rede_bloqueada_na_free(window):
    sec = _section(window)
    assert sec.locked and not hasattr(sec, "mode_group")


def test_textos_de_ajuda_do_firewall():
    assert "Permitir" in mariadb.env_has_firewall_hint() or "ufw" in mariadb.env_has_firewall_hint()
    pw = mariadb.new_password()
    assert len(pw) == 14 and pw.count("-") == 2 and not set("0o1il") & set(pw)
    assert dls.MODES == ["local", "client", "server"]
