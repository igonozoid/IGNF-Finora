"""Backup e restauração do banco local.

Usa a API de backup do SQLite: a cópia sai consistente mesmo com o app aberto.
Um backup é o próprio arquivo do banco (.db), então dá para guardar em pendrive, nuvem etc.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from finora.core import db

AUTO_PREFIX = "auto-"
SAFETY_PREFIX = "antes-de-restaurar-"
KEEP_AUTO = 7
REQUIRED_TABLES = {"entities", "accounts", "categories", "entries"}


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    modified: datetime
    size: int
    name: str            # nome do perfil (entidade) dentro do backup
    accounts: int
    entries: int

    @property
    def size_label(self) -> str:
        kb = self.size / 1024
        return f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB".replace(".", ",")


def suggested_name(now: datetime | None = None) -> str:
    return f"finora-backup-{(now or datetime.now()):%Y-%m-%d_%H%M}.db"


def _copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(src)
    d = sqlite3.connect(dest)
    try:
        with d:
            s.backup(d)
    finally:
        d.close()
        s.close()


def backup_to(dest: Path, db_file: Path | None = None) -> Path:
    """Copia o banco para `dest` (sobrescreve se existir)."""
    dest, src = Path(dest), Path(db_file or db.DB_FILE)
    if dest.resolve() == src.resolve():
        raise ValueError("Escolha outro lugar: esse é o próprio arquivo de dados do app.")
    if dest.exists():
        dest.unlink()
    _copy(src, dest)
    return dest


def inspect_backup(path: Path) -> BackupInfo:
    """Confere se o arquivo é um backup do Finora e lê um resumo. Levanta ValueError se não for."""
    path = Path(path)
    if not path.is_file():
        raise ValueError("Arquivo não encontrado.")
    try:
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("O arquivo de backup está danificado.")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES <= tables:
                raise ValueError("Esse arquivo não é um backup do IGNF Finora.")
            name = con.execute("SELECT name FROM entities ORDER BY id LIMIT 1").fetchone()
            n_acc = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
            n_ent = con.execute("SELECT count(*) FROM entries").fetchone()[0]
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        raise ValueError("Esse arquivo não é um backup do IGNF Finora.") from e
    st = path.stat()
    return BackupInfo(path, datetime.fromtimestamp(st.st_mtime), st.st_size,
                      name[0] if name else "(sem perfil)", n_acc, n_ent)


def restore_from(path: Path, db_file: Path | None = None, backup_dir: Path | None = None,
                 now: datetime | None = None) -> Path:
    """Troca o banco atual pelo backup. Antes, guarda uma cópia do atual e devolve onde ela ficou.
    Depois de restaurar, o app precisa ser reaberto."""
    inspect_backup(path)                                   # não restaura arquivo inválido
    db_file = Path(db_file or db.DB_FILE)
    if Path(path).resolve() == db_file.resolve():
        raise ValueError("Esse é o arquivo de dados que já está em uso.")
    safety = Path(backup_dir or db.BACKUP_DIR) / f"{SAFETY_PREFIX}{(now or datetime.now()):%Y-%m-%d_%H%M%S}.db"
    if db_file.exists():
        backup_to(safety, db_file)
    db.engine.dispose()                                    # fecha as conexões abertas do app
    _copy(Path(path), db_file)
    return safety


def auto_backup(backup_dir: Path | None = None, db_file: Path | None = None, keep: int = KEEP_AUTO,
                now: datetime | None = None) -> Path | None:
    """Um backup automático por dia (o primeiro ao abrir o app). Mantém só os `keep` mais recentes."""
    backup_dir = Path(backup_dir or db.BACKUP_DIR)
    now = now or datetime.now()
    if list(backup_dir.glob(f"{AUTO_PREFIX}{now:%Y-%m-%d}_*.db")):
        return None
    made = backup_to(backup_dir / f"{AUTO_PREFIX}{now:%Y-%m-%d_%H%M}.db", db_file)
    for old in sorted(backup_dir.glob(f"{AUTO_PREFIX}*.db"))[:-keep]:
        old.unlink()
    return made


def list_local(backup_dir: Path | None = None) -> list[BackupInfo]:
    """Backups guardados na pasta do app (automáticos e de antes de restaurar), mais novos primeiro."""
    backup_dir = Path(backup_dir or db.BACKUP_DIR)
    out = []
    for p in backup_dir.glob("*.db"):
        try:
            out.append(inspect_backup(p))
        except ValueError:
            continue
    return sorted(out, key=lambda b: b.modified, reverse=True)
