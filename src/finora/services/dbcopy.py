"""Cópia completa de um banco do Finora para outro (este PC ⇄ servidor).

Usos: levar os dados deste computador para o Finora Servidor; e, no modo servidor, fazer o backup num
arquivo .db (o mesmo formato do backup de sempre) e restaurar a partir dele.
"""
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

import finora.models  # noqa: F401  (registra as tabelas)
from finora.core import db
from finora.models import Base, Entity

BATCH = 500


@dataclass(frozen=True)
class CopyResult:
    tables: int
    rows: int


def _fk_off(conn) -> None:
    if conn.dialect.name in ("mysql", "mariadb"):
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")


def _fk_on(conn) -> None:
    if conn.dialect.name in ("mysql", "mariadb"):
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")


def has_data(eng: Engine) -> bool:
    """O banco já tem alguma entidade (dados de alguém)?"""
    from sqlalchemy import inspect
    if not inspect(eng).has_table("entities"):
        return False
    with eng.connect() as conn:
        return bool(conn.scalar(select(func.count()).select_from(Entity.__table__)))


def copy_all(src: Engine, dst: Engine, progress=None) -> CopyResult:
    """Apaga o que houver no destino e copia todas as tabelas da origem (mesma versão do esquema).
    O destino é criado/atualizado pelas migrações antes. `progress(tabela, linhas)` é opcional."""
    db.init_db(src)
    db.init_db(dst)
    tables = Base.metadata.sorted_tables                 # pais antes dos filhos
    total = 0
    if dst.dialect.name == "sqlite":
        # SQLite: as chaves estrangeiras só desligam fora de transação
        with dst.connect() as c:
            c.exec_driver_sql("PRAGMA foreign_keys=OFF")
            c.commit()
            total = _copy(src, c, tables, progress)
            c.exec_driver_sql("PRAGMA foreign_keys=ON")
            c.commit()
    else:
        with dst.connect() as c:
            total = _copy(src, c, tables, progress)
    return CopyResult(len(tables), total)


def _copy(src: Engine, dst_conn, tables, progress) -> int:
    total = 0
    with dst_conn.begin():
        _fk_off(dst_conn)
        for table in reversed(tables):
            dst_conn.execute(table.delete())
        with src.connect() as s:
            for table in tables:
                rows = [dict(r) for r in s.execute(select(table)).mappings()]
                for i in range(0, len(rows), BATCH):
                    dst_conn.execute(table.insert(), rows[i:i + BATCH])
                total += len(rows)
                if progress:
                    progress(table.name, len(rows))
        _fk_on(dst_conn)
    return total


def export_to_file(src: Engine, path: Path) -> Path:
    """Backup do banco do servidor num arquivo .db (SQLite), que abre em qualquer Finora."""
    path = Path(path)
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    dst = db.make_engine(f"sqlite:///{path}")
    try:
        copy_all(src, dst)
    finally:
        dst.dispose()
    return path


def import_from_file(path: Path, dst: Engine) -> CopyResult:
    """Restaura um backup .db no banco do servidor (troca tudo o que está lá)."""
    src = db.make_engine(f"sqlite:///{Path(path)}")
    try:
        return copy_all(src, dst)
    finally:
        src.dispose()
