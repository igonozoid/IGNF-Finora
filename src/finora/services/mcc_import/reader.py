"""Leitor do banco do MCC (formato do clone igonozoid/MCC_CLAUDE-REA, `mcc-desktop/mcc/core/db.py`).

O arquivo original nunca é aberto: ele (e os arquivos -wal/-shm, se o MCC estiver usando) é copiado para uma pasta
temporária e a cópia é aberta em modo somente leitura. Assim a importação não mexe no MCC, mesmo com ele aberto.
O banco do MCC é SQLite; por isso aqui se usa o sqlite3 direto (não é o banco do Finora).
"""
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

# Tabelas e colunas que o importador usa. As três últimas tabelas só existem no MCC desktop (o clone web não as tem).
REQUIRED = {
    "empresas": {"id", "nome", "pessoa", "documento"},
    "contas": {"id", "empresa_id", "descricao", "tipo", "saldo_inicial", "ativa"},
    "centros": {"id", "empresa_id", "nome", "aplica_despesa", "aplica_receita", "orcamento", "projecao"},
    "pessoas": {"id", "empresa_id", "tipo", "pessoa", "nome", "documento"},
    "itens": {"id", "empresa_id", "tipo", "descricao"},
    "lancamentos": {"id", "empresa_id", "tipo", "data_mov", "descricao", "valor", "situacao", "vencimento",
                    "data_pagamento", "conta_id", "grupo", "excluido_em"},
    "movbancarias": {"id", "empresa_id", "tipo", "situacao", "data", "origem_id", "destino_id", "valor"},
    "usuarios": {"id", "nome", "email", "admin", "ativo"},
}
OPTIONAL = ("ofx_importados", "usuario_empresas", "pessoas_extra", "empresa_config", "empresa_logos")


@dataclass(frozen=True)
class CompanySummary:
    id: int
    name: str
    person_type: str           # PF | PJ
    document: str
    entries: int               # lançamentos (fora os excluídos)
    deleted: int               # na lixeira do MCC
    first_day: str | None      # data de movimento mais antiga (AAAA-MM-DD)
    last_day: str | None


@dataclass(frozen=True)
class Summary:
    path: str
    companies: list[CompanySummary]
    rows: dict[str, int]                             # linhas por tabela
    shared_accounts: int                             # contas sem empresa (compartilhadas)
    shared_people: int
    missing_optional: list[str] = field(default_factory=list)

    @property
    def total_entries(self) -> int:
        return sum(c.entries for c in self.companies)


class NotMccError(ValueError):
    pass


@contextmanager
def open_copy(path: str | Path):
    """Abre uma cópia do banco do MCC, só para leitura. Uso: `with open_copy(caminho) as mcc: ...`.
    Levanta NotMccError com mensagem pronta se o arquivo não for um banco do MCC."""
    src = Path(path)
    if not src.is_file():
        raise NotMccError(f"Arquivo não encontrado: {src}")
    with tempfile.TemporaryDirectory(prefix="finora-mcc-") as tmp:
        copy = Path(tmp) / "mcc.db"
        shutil.copy2(src, copy)
        for extra in ("-wal", "-shm"):                     # dados que o MCC ainda não gravou no arquivo principal
            side = src.with_name(src.name + extra)
            if side.is_file():
                shutil.copy2(side, copy.with_name(copy.name + extra))
        con = sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            check(con)
            yield con
        finally:
            con.close()


def check(con: sqlite3.Connection) -> list[str]:
    """Confere se é um banco do MCC com tudo que o importador usa. Devolve as tabelas opcionais que faltam."""
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as exc:
        raise NotMccError("Esse arquivo não é um banco de dados do MCC (não consegui ler).") from exc
    missing = [t for t in REQUIRED if t not in tables]
    if missing:
        raise NotMccError("Esse arquivo não parece ser do MCC: faltam as tabelas " + ", ".join(missing) + ".")
    for table, cols in REQUIRED.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        lack = sorted(cols - have)
        if lack:
            raise NotMccError(f"Banco do MCC numa versão que o Finora não conhece: a tabela {table} não tem "
                              + ", ".join(lack) + ".")
    return [t for t in OPTIONAL if t not in tables]


def rows(con: sqlite3.Connection, table: str, where: str = "", args: tuple = ()) -> list[dict]:
    """Linhas de uma tabela do MCC como dicionários (para o mapeamento). Tabela opcional ausente: lista vazia."""
    if table not in REQUIRED and table not in OPTIONAL:
        raise ValueError(f"Tabela desconhecida do MCC: {table}")
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return []
    sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + " ORDER BY rowid"
    return [dict(r) for r in con.execute(sql, args)]


def summary(con: sqlite3.Connection, path: str = "") -> Summary:
    """O que há no banco: empresas (contas controle) com quantos lançamentos e de quando a quando."""
    missing = check(con)
    count = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    companies = []
    for e in con.execute("SELECT id, nome, pessoa, documento FROM empresas ORDER BY id"):
        live = "FROM lancamentos WHERE empresa_id=? AND excluido_em IS NULL"
        first, last = con.execute(f"SELECT MIN(data_mov), MAX(data_mov) {live}", (e["id"],)).fetchone()
        companies.append(CompanySummary(
            e["id"], e["nome"], "PJ" if e["pessoa"] == "J" else "PF", e["documento"] or "",
            count(f"SELECT COUNT(*) {live}", e["id"]),
            count("SELECT COUNT(*) FROM lancamentos WHERE empresa_id=? AND excluido_em IS NOT NULL", e["id"]),
            first, last))
    tables = [t for t in (*REQUIRED, *OPTIONAL) if t not in missing]
    return Summary(path, companies, {t: count(f"SELECT COUNT(*) FROM {t}") for t in tables},
                   count("SELECT COUNT(*) FROM contas WHERE empresa_id IS NULL"),
                   count("SELECT COUNT(*) FROM pessoas WHERE empresa_id IS NULL"), missing)


def read_summary(path: str | Path) -> Summary:
    """Atalho: abre a cópia, resume e fecha."""
    with open_copy(path) as con:
        return summary(con, str(path))
