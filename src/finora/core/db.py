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

def init_db():
    import finora.models  # noqa: registra modelos
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns():
    """Provisório, até o Alembic (1ª versão publicada): cria no banco local as colunas
    novas dos modelos. Só adiciona colunas que aceitam vazio; nunca altera nem apaga."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or not col.nullable:
                    continue
                conn.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}')
                for idx in table.indexes:
                    if [c.name for c in idx.columns] == [col.name]:
                        idx.create(conn, checkfirst=True)
