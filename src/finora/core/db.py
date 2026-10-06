from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from finora.core.paths import DATA_DIR

DB_FILE = DATA_DIR / "finora.db"
BACKUP_DIR = DATA_DIR / "backups"   # backups automáticos e cópias de segurança antes de restaurar


def sqlite_pragmas(eng):
    """O SQLite só confere chaves estrangeiras se isso for pedido em cada conexão.
    Sem isso, dá para gravar um lançamento apontando para uma conta que não existe."""
    if eng.dialect.name != "sqlite":
        return eng

    @event.listens_for(eng, "connect")
    def _on_connect(dbapi_con, _record):
        cur = dbapi_con.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return eng


engine = sqlite_pragmas(create_engine(f"sqlite:///{DB_FILE}", future=True))
Session = sessionmaker(engine)

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
BASELINE = "0001"   # 1ª revisão do Alembic = esquema das etapas 1 a 8


def _alembic(connection):
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["connection"] = connection
    return cfg


def schema_state(eng=None) -> tuple[str | None, str, bool]:
    """(revisão do banco, revisão mais nova, banco já tem tabelas do Finora?)."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    with (eng or engine).connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        head = ScriptDirectory.from_config(_alembic(conn)).get_current_head()
        has_tables = inspect(conn).has_table("entities")
    return current, head, has_tables


def init_db(eng=None, backup_dir: Path | None = None) -> str | None:
    """Cria ou atualiza o banco com as migrações do Alembic. Antes de atualizar um banco que já tem
    dados, guarda uma cópia em data/backups. Retorna o caminho dessa cópia (ou None)."""
    from alembic import command
    eng = eng or engine
    current, head, has_tables = schema_state(eng)
    if current is None and has_tables:
        # Banco criado antes do Alembic: completa colunas que faltarem e marca como "versão inicial".
        with eng.begin() as conn:
            _legacy_add_missing_columns(conn)
            command.stamp(_alembic(conn), BASELINE)
        current = BASELINE
    if current == head:
        return None
    safety = None
    if has_tables and eng.url.database not in (None, "", ":memory:"):
        from finora.services import backup
        safety = str(backup.backup_to(Path(backup_dir or BACKUP_DIR) / f"{backup.UPDATE_PREFIX}{current}-para-{head}.db",
                                      Path(eng.url.database)))
    with eng.connect() as conn:
        sqlite = eng.dialect.name == "sqlite"
        if sqlite:
            # O SQLite altera tabela recriando-a (copia, apaga a antiga, renomeia). Com as chaves estrangeiras
            # ligadas, apagar "entities" falharia porque contas e lançamentos apontam para ela. Desliga só
            # durante a migração (fora de transação, senão o SQLite ignora) e confere tudo no fim.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        try:
            with conn.begin():
                command.upgrade(_alembic(conn), "head")
                if sqlite and conn.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                    raise RuntimeError("A atualização do banco deixou referências quebradas; nada foi alterado.")
        finally:
            if sqlite:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()
    return safety


# Colunas que entraram ANTES do Alembic (até a revisão 0001). Tudo o que veio depois é migração.
_PRE_ALEMBIC = {"entries": {"series_id": "VARCHAR(32)"}}


def _legacy_add_missing_columns(conn):
    """Só para bancos de antes do Alembic: completa o que a revisão 0001 já tinha (ex.: entries.series_id),
    para o banco ficar igual à 0001 antes de receber as migrações seguintes. Nunca altera nem apaga."""
    insp = inspect(conn)
    for table, cols in _PRE_ALEMBIC.items():
        if not insp.has_table(table):
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols.items():
            if name not in have:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}')
    if "series_id" not in {i["column_names"][0] for i in insp.get_indexes("entries") if i["column_names"]}:
        conn.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_entries_series_id ON entries (series_id)')
