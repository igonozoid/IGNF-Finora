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


def _pre_alembic(path, drop_series=False):
    """Banco como era antes do Alembic: o esquema da revisão 0001, sem a tabela alembic_version."""
    from alembic import command
    eng = _engine(path)
    with eng.begin() as conn:
        command.upgrade(db._alembic(conn), db.BASELINE)
        conn.exec_driver_sql("DROP TABLE alembic_version")
    eng.dispose()
    if drop_series:                                               # ainda mais antigo: antes da etapa 4
        con = sqlite3.connect(path)
        con.execute("DROP INDEX ix_entries_series_id")
        con.execute("ALTER TABLE entries DROP COLUMN series_id")
        con.commit()
        con.close()
    return _engine(path)


def test_banco_de_antes_do_alembic_e_reconhecido_e_atualizado(tmp_path):
    """Como o banco do usuário: sem alembic_version. É marcado como 0001 e recebe as migrações seguintes."""
    eng = _pre_alembic(tmp_path / "antigo.db")
    safety = db.init_db(eng, tmp_path / "bk")
    _, head, _ = db.schema_state(eng)
    assert _revision(eng) == head
    assert safety and "antes-de-atualizar-0001" in safety          # guardou cópia antes de migrar
    cols = {c["name"] for c in inspect(eng).get_columns("accounts")}
    assert {"closing_day", "due_day", "credit_limit"} <= cols
    eng.dispose()


def test_banco_bem_antigo_ganha_colunas_que_faltam(tmp_path):
    eng = _pre_alembic(tmp_path / "bem-antigo.db", drop_series=True)
    db.init_db(eng, tmp_path / "bk")
    cols = {c["name"] for c in inspect(eng).get_columns("entries")}
    _, head, _ = db.schema_state(eng)
    assert "series_id" in cols and _revision(eng) == head
    with eng.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diffs == []                                            # terminou igual aos modelos
    eng.dispose()


def test_atualizacao_guarda_copia_antes(tmp_path, monkeypatch):
    eng = _engine(tmp_path / "finora.db")
    db.init_db(eng, tmp_path / "bk")
    monkeypatch.setattr(db, "schema_state", lambda e=None: ("0001", "9999", True))   # finge revisão nova
    safety = db.init_db(eng, tmp_path / "bk")
    assert safety and safety.endswith("antes-de-atualizar-0001-para-9999.db")
    assert (tmp_path / "bk" / "antes-de-atualizar-0001-para-9999.db").exists()
    eng.dispose()


def test_banco_com_dados_ganha_admin_e_valores_na_moeda_principal(tmp_path):
    """Banco antigo com uma entidade e um lançamento: após migrar, há um administrador sem senha com acesso a
    ela, e o valor na moeda principal (base_amount) é o próprio valor."""
    eng = _pre_alembic(tmp_path / "com-dados.db")
    with eng.begin() as conn:
        conn.exec_driver_sql("INSERT INTO entities (id, name, currency) VALUES (1, 'Rodrigo', 'BRL')")
        conn.exec_driver_sql("INSERT INTO accounts (id, entity_id, name, kind, currency, opening_balance, is_active)"
                             " VALUES (1, 1, 'Nubank', 'bank', 'BRL', 0, 1)")
        conn.exec_driver_sql("INSERT INTO entries (entity_id, kind, account_id, amount, description, "
                             "competence_date, due_date, status) VALUES (1, 'expense', 1, 42.5, 'Luz', "
                             "'2026-10-01', '2026-10-01', 'pending')")
    db.init_db(eng, tmp_path / "bk")
    with eng.connect() as conn:
        users = conn.exec_driver_sql("SELECT name, is_admin, password_hash FROM users").all()
        access = conn.exec_driver_sql("SELECT user_id, entity_id FROM user_entities").all()
        base = conn.exec_driver_sql("SELECT base_amount FROM entries").scalar()
        ent = conn.exec_driver_sql("SELECT person_type, is_active FROM entities").one()
    assert [(u[0], bool(u[1]), u[2]) for u in users] == [("Rodrigo", True, None)]
    assert access == [(1, 1)] and float(base) == 42.5 and (ent[0], bool(ent[1])) == ("PF", True)
    eng.dispose()
