import os
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finora.core import db, secret, settings
from finora.models import Entry, User
from finora.services import accounts, attachments, dbcopy, entries, setup
from finora.services.entries import EntryData


def _filled(path):
    eng = db.make_engine(f"sqlite:///{path}")
    db.init_db(eng)
    with Session(eng) as s:
        p = setup.run_first_setup(s, name="Ana", currency="BRL", account_name="Banco", account_kind="bank",
                                  balance=D("100"))
        bank = accounts.list_accounts(s, p.id)[0].id
        (eid,) = entries.create(s, p.id, EntryData(kind="expense", description="Luz", amount=D("90"),
                                                   due_date=date(2026, 10, 5), account_id=bank))
        f = path.parent / "nota.pdf"
        f.write_bytes(b"%PDF anexo")
        attachments.add(s, eid, f)
    return eng


def _counts(eng):
    with Session(eng) as s:
        return (s.scalar(select(func.count(Entry.id))), s.scalar(select(func.count(User.id))),
                s.scalar(select(func.count()).select_from(db_tables()["attachments"])))


def db_tables():
    from finora.models import Base
    return Base.metadata.tables


def test_copia_completa_entre_bancos_e_backup_em_arquivo(tmp_path):
    src = _filled(tmp_path / "origem.db")
    dst = db.make_engine(f"sqlite:///{tmp_path / 'destino.db'}")
    assert not dbcopy.has_data(dst)
    r = dbcopy.copy_all(src, dst)
    assert r.rows > 50 and dbcopy.has_data(dst)
    assert _counts(dst) == _counts(src) == (1, 1, 1)
    with Session(dst) as s:                                      # o anexo veio inteiro
        assert attachments.content(s, 1)[1] == b"%PDF anexo"
    # copiar de novo substitui (não duplica)
    dbcopy.copy_all(src, dst)
    assert _counts(dst) == (1, 1, 1)
    out = dbcopy.export_to_file(dst, tmp_path / "bk" / "servidor.db")
    back = db.make_engine(f"sqlite:///{out}")
    assert _counts(back) == (1, 1, 1)
    for e in (src, dst, back):
        e.dispose()


COPY_URL = os.environ.get("FINORA_TEST_COPY_URL")      # banco VAZIO de um servidor de teste


@pytest.mark.skipif(not COPY_URL, reason="sem servidor de teste (FINORA_TEST_COPY_URL)")
def test_levar_dados_para_o_mariadb_e_trazer_de_volta(tmp_path):
    from sqlalchemy import create_engine
    src = _filled(tmp_path / "origem.db")
    server = create_engine(COPY_URL)
    dbcopy.copy_all(src, server)
    assert _counts(server) == (1, 1, 1)
    with Session(server) as s:                                    # o servidor continua aceitando lançamentos
        bank = accounts.list_accounts(s, 1)[0].id
        entries.create(s, 1, EntryData(kind="income", description="Salário", amount=D("10"),
                                       due_date=date(2026, 10, 6), account_id=bank))
    out = dbcopy.export_to_file(server, tmp_path / "srv.db")
    assert _counts(db.make_engine(f"sqlite:///{out}"))[0] == 2
    server.dispose()


def test_senha_guardada_protegida(tmp_path):
    stored = secret.protect("s3nh@ forte")
    assert "s3nh" not in stored and secret.unprotect(stored) == "s3nh@ forte"
    assert secret.protect("") == "" and secret.unprotect("") == ""
    cfg = settings.DbConfig("client", "192.168.0.10", 3306, "finora", "finora", "p@ss/1")
    settings.set_db_config(cfg)
    assert settings.get_db_config() == cfg
    assert cfg.url() == "mysql+pymysql://finora:p%40ss%2F1@192.168.0.10:3306/finora?charset=utf8mb4"
    assert "p@ss" not in (tmp_path / "finora.ini").read_text(encoding="utf-8")
