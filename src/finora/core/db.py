from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from finora.core.paths import DATA_DIR
from finora.models.base import Base

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
    with eng.begin() as conn:
        command.upgrade(_alembic(conn), "head")
    return safety


def _legacy_add_missing_columns(conn):
    """Só para bancos de antes do Alembic: cria colunas que entraram nos modelos depois
    (ex.: entries.series_id). Só adiciona colunas que aceitam vazio; nunca altera nem apaga."""
    import finora.models  # noqa: F401 — registra os modelos
    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have or not col.nullable:
                continue
            conn.exec_driver_sql(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(conn.dialect)}')
            for idx in table.indexes:
                if [c.name for c in idx.columns] == [col.name]:
                    idx.create(conn, checkfirst=True)
