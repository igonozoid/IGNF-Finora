"""Ambiente do Alembic. O app chama as migrações sozinho (core/db.init_db), passando a conexão;
pela linha de comando (alembic revision --autogenerate …) usa o banco de data/finora.db."""
from alembic import context

import finora.models  # noqa: F401 — registra as tabelas
from finora.models.base import Base

target_metadata = Base.metadata


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _migrate(connection)
        return
    from finora.core.db import engine
    with engine.begin() as conn:
        _migrate(conn)


def _migrate(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,   # SQLite não altera colunas direto; o Alembic recria a tabela por baixo
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("O Finora não usa migrações offline (SQL gerado). Rode com o banco conectado.")
run()
