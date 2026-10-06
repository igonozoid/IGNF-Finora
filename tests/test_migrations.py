import sqlite3

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import finora.models  # noqa: F401
from finora.core import db
from finora.models import Base


def _engine(path):
    return db.sqlite_pragmas(create_engine(f"sqlite:///{path}"))


def _revision(eng):
    with eng.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def test_banco_novo_e_criado_pelas_migracoes(tmp_path):
    eng = _engine(tmp_path / "novo.db")
    assert db.init_db(eng, tmp_path / "bk") is None             # banco vazio: nada para guardar
    _, head, _ = db.schema_state(eng)
    assert _revision(eng) == head
    assert {"entities", "accounts", "categories", "contacts", "cost_centers", "entries"} <= set(inspect(eng).get_table_names())
    assert not (tmp_path / "bk").exists()
    eng.dispose()


def test_migracoes_batem_com_os_modelos(tmp_path):
    """Se alguém mudar um modelo e esquecer a migração, este teste quebra."""
    eng = _engine(tmp_path / "m.db")
    db.init_db(eng, tmp_path / "bk")
    with eng.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diffs == []
    eng.dispose()


def test_banco_de_antes_do_alembic_e_reconhecido(tmp_path):
    """Como o banco do usuário: criado com create_all, sem tabela alembic_version."""
    eng = _engine(tmp_path / "antigo.db")
    Base.metadata.create_all(eng)
    assert db.init_db(eng, tmp_path / "bk") is None
    assert _revision(eng) == db.BASELINE
    eng.dispose()


def test_banco_bem_antigo_ganha_colunas_que_faltam(tmp_path):
    path = tmp_path / "bem-antigo.db"
    eng = _engine(path)
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path)                                   # simula o banco de antes da etapa 4
    con.execute("DROP INDEX ix_entries_series_id")
    con.execute("ALTER TABLE entries DROP COLUMN series_id")
    con.commit()
    con.close()
    eng = _engine(path)
    db.init_db(eng, tmp_path / "bk")
    cols = {c["name"] for c in inspect(eng).get_columns("entries")}
    assert "series_id" in cols and _revision(eng) == db.BASELINE
    eng.dispose()


def test_atualizacao_guarda_copia_antes(tmp_path, monkeypatch):
    eng = _engine(tmp_path / "finora.db")
    db.init_db(eng, tmp_path / "bk")
    monkeypatch.setattr(db, "schema_state", lambda e=None: ("0001", "9999", True))   # finge revisão nova
    safety = db.init_db(eng, tmp_path / "bk")
    assert safety and safety.endswith("antes-de-atualizar-0001-para-9999.db")
    assert (tmp_path / "bk" / "antes-de-atualizar-0001-para-9999.db").exists()
    eng.dispose()
