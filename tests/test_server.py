import os
import shutil
import sys
import zipfile
from pathlib import Path

import pymysql
import pytest

from finora.server import mariadb


def test_descompacta_sem_a_pasta_de_cima_e_sem_testes(tmp_path):
    pkg = tmp_path / "mariadb-11.4.13-winx64.zip"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("mariadb-11.4.13-winx64/bin/mariadbd.exe", b"x")
        z.writestr("mariadb-11.4.13-winx64/share/errmsg.sys", b"x")
        z.writestr("mariadb-11.4.13-winx64/mysql-test/t/a.test", b"x")
        z.writestr("mariadb-11.4.13-winx64/bin/mariadbd.pdb", b"x")
    dest = tmp_path / "servidor" / "mariadb"
    mariadb._extract(pkg, dest)
    assert (dest / "bin" / "mariadbd.exe").exists() and (dest / "share" / "errmsg.sys").exists()
    assert not (dest / "mysql-test").exists() and not (dest / "bin" / "mariadbd.pdb").exists()


def test_configuracao_do_servidor(tmp_path):
    lay = mariadb.layout(tmp_path)
    lay.root.mkdir(parents=True, exist_ok=True)
    mariadb.write_config(lay, 3307)
    cnf = lay.config.read_text(encoding="utf-8")
    assert "port=3307" in cnf and "bind-address=0.0.0.0" in cnf and "max_allowed_packet=32M" in cnf
    assert f"datadir={(tmp_path / 'dados').as_posix()}" in cnf
    assert not mariadb.installed(lay)
    with pytest.raises(mariadb.ServerError, match="Baixe"):
        mariadb.initialize(lay, "x")


@pytest.mark.parametrize("code, msg", [(1045, "recusou a senha"), (2003, "Não encontrei o servidor")])
def test_mensagens_de_conexao(monkeypatch, code, msg):
    def fail(**k):
        raise pymysql.err.OperationalError(code, "erro")

    monkeypatch.setattr(pymysql, "connect", fail)
    with pytest.raises(mariadb.ServerError, match=msg):
        mariadb.check_connection("10.0.0.5", 3306, "x")


def test_porta_fechada_e_enderecos():
    assert not mariadb.is_listening(1)            # porta 1: ninguém escutando
    assert all(ip.count(".") == 3 for ip in mariadb.lan_addresses())


# Teste de verdade, opcional: aponte FINORA_TEST_MARIADB_DIR para um MariaDB descompactado (pasta com bin/).
REAL = os.environ.get("FINORA_TEST_MARIADB_DIR")


@pytest.mark.skipif(not REAL or sys.platform != "win32", reason="sem MariaDB de teste (FINORA_TEST_MARIADB_DIR)")
def test_preparar_ligar_conectar_e_desligar_de_verdade(tmp_path):
    lay = mariadb.layout(tmp_path)
    shutil.copytree(Path(REAL), lay.programs, ignore=shutil.ignore_patterns("mysql-test", "*.pdb", "include"))
    port = 33399
    mariadb.initialize(lay, "raiz-teste", port)
    mariadb.start(lay, port)
    try:
        mariadb.wait_ready(port, "root", "raiz-teste")
        mariadb.setup_database(port, "raiz-teste", "app-teste")
        mariadb.check_connection("127.0.0.1", port, "app-teste")
    finally:
        mariadb.stop(lay, port, "raiz-teste")
    assert not mariadb.is_listening(port)
