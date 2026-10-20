"""Backup antes de importar e importação tudo-ou-nada (Fase 2.9)."""
import shutil
import sqlite3
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from finora.core import db
from finora.models import Base, Entity, Entry, ImportMap
from finora.services import backup, entity_admin, period_lock
from finora.services.mcc_import import mapper, reader

DATA = Path(__file__).parent / "data"


@pytest.fixture
def mcc(tmp_path):
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    return p


def _count(s, model):
    return s.scalar(select(func.count(model.id)))


def _boom(self):
    raise RuntimeError("falhou no meio")


def test_faz_backup_e_importa(plus, mcc, tmp_path):
    eng = db.sqlite_pragmas(create_engine(f"sqlite:///{tmp_path / 'finora.db'}"))
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        entity_admin.create(s, name="Minha casa", person_type="PF")
        with reader.open_copy(mcc) as con:
            r = mapper.import_safely(s, con, backup_dir=tmp_path / "bk", now=datetime(2026, 10, 16, 9, 30))
        assert _count(s, Entity) == 3 and _count(s, Entry) > 0
    eng.dispose()
    assert r.backup == tmp_path / "bk" / f"{backup.IMPORT_PREFIX}2026-10-16_093000.db"
    info = backup.inspect_backup(r.backup)                       # o retrato de antes: só a entidade que já tinha
    assert (info.name, info.entries) == ("Minha casa", 0)
    assert [b.path for b in backup.list_local(tmp_path / "bk")] == [r.backup]   # aparece para restaurar


def test_backup_conforme_o_banco(session, plus, mcc, tmp_path):
    """Banco só de memória (testes): sem backup. Banco de verdade — arquivo ou servidor MariaDB: a cópia de antes
    da importação sai num .db que abre em qualquer Finora (no servidor, pelo dbcopy)."""
    with reader.open_copy(mcc) as con:
        r = mapper.import_safely(session, con, backup_dir=tmp_path / "bk")
    assert r.entities
    url = session.get_bind().url
    if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:"):
        assert r.backup is None
    else:
        assert r.backup.name.startswith(backup.IMPORT_PREFIX) and backup.inspect_backup(r.backup)


def test_erro_no_meio_nao_grava_nada(session, plus, mcc, monkeypatch):
    mine = entity_admin.create(session, name="Minha casa", person_type="PF")
    monkeypatch.setattr(mapper._Importer, "user_rows", _boom)     # depois de entidades, contas e lançamentos
    with reader.open_copy(mcc) as con, pytest.raises(RuntimeError):
        mapper.import_safely(session, con)
    assert [e.id for e in session.scalars(select(Entity))] == [mine]
    assert (_count(session, Entry), _count(session, ImportMap)) == (0, 0)


def test_reimportacao_que_falha_deixa_a_anterior_inteira(session, plus, mcc, monkeypatch):
    with reader.open_copy(mcc) as con:
        r = mapper.import_safely(session, con)
    con = sqlite3.connect(mcc)
    con.execute("UPDATE lancamentos SET valor=500 WHERE id=1")         # período fechado: reabre na reimportação
    con.execute("DELETE FROM lancamentos WHERE id=21")
    con.commit()
    con.close()
    monkeypatch.setattr(mapper._Importer, "user_rows", _boom)
    with reader.open_copy(mcc) as c, pytest.raises(RuntimeError):
        mapper.import_safely(session, c)
    assert session.get(Entry, r.entries[1]).amount == D("412.37")
    assert session.get(Entry, r.entries[21]) is not None
    assert period_lock.locked_through(session, r.entities[1]) == datetime(2026, 3, 31).date()


def test_previa_confere_e_nao_grava_nada(session, plus, mcc):
    with reader.open_copy(mcc) as con:
        r, rep = mapper.preview(session, con)
    assert r.entities and rep.ok, rep.problems
    assert (_count(session, Entity), _count(session, Entry), _count(session, ImportMap)) == (0, 0, 0)
    assert mapper.already_imported(session) == set()
    with reader.open_copy(mcc) as con:
        mapper.import_safely(session, con, companies=[2])
    assert mapper.already_imported(session) == {2}
