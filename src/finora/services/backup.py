"""Backup e restauração do banco local.

Usa a API de backup do SQLite: a cópia sai consistente mesmo com o app aberto.
Um backup é o próprio arquivo do banco (.db), então dá para guardar em pendrive, nuvem etc.
"""
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from finora.core import db

AUTO_PREFIX = "auto-"
SAFETY_PREFIX = "antes-de-restaurar-"
UPDATE_PREFIX = "antes-de-atualizar-"   # cópia feita pelo init_db antes de aplicar migrações
KEEP_AUTO = 7
KEEP_CLOUD = 14
CLOUD_SUBDIR = "IGNF-Finora"            # dentro da pasta da nuvem
CLOUD_PREFIX = "finora-"
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
    """Copia o banco para `dest` (sobrescreve se existir). No modo servidor (sem `db_file`), exporta o banco do
    servidor para um arquivo .db — o mesmo formato, que abre em qualquer Finora."""
    if db_file is None and db.is_server():
        from finora.services import dbcopy
        return dbcopy.export_to_file(db.engine, Path(dest))
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
    if db_file is None and db.is_server():                 # modo servidor: troca os dados do servidor
        from finora.services import dbcopy
        safety = Path(backup_dir or db.BACKUP_DIR) / f"{SAFETY_PREFIX}{(now or datetime.now()):%Y-%m-%d_%H%M%S}.db"
        dbcopy.export_to_file(db.engine, safety)
        dbcopy.import_from_file(Path(path), db.engine)
        return safety
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


# ---------- backup numa pasta sincronizada com a nuvem ----------
def cloud_candidates(home: Path | None = None) -> list[tuple[str, Path]]:
    """Pastas de OneDrive / Google Drive / Dropbox / iCloud encontradas neste computador."""
    home = Path(home or Path.home())
    found: list[tuple[str, Path]] = []

    def add(label: str, path: Path | str | None):
        if path and Path(path).is_dir() and all(Path(path) != p for _l, p in found):
            found.append((label, Path(path)))

    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        add("OneDrive", os.environ.get(var))
    for name in ("OneDrive", "Dropbox", "Google Drive", "GoogleDrive", "Meu Drive", "My Drive"):
        add("Google Drive" if "Drive" in name and "One" not in name else name, home / name)
    if sys.platform == "win32":
        for letter in "GHIJ":                              # Google Drive para computador monta uma unidade
            for sub in ("My Drive", "Meu Drive"):
                add("Google Drive", Path(f"{letter}:/{sub}"))
    cloud = home / "Library" / "CloudStorage"            # macOS
    if cloud.is_dir():
        for p in sorted(cloud.iterdir()):
            label = ("Google Drive" if p.name.startswith("GoogleDrive") else
                     "OneDrive" if p.name.startswith("OneDrive") else
                     "Dropbox" if p.name.startswith("Dropbox") else p.name)
            add(label, p)
    add("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs")
    return found


def cloud_backup(folder: Path, db_file: Path | None = None, keep: int = KEEP_CLOUD,
                 now: datetime | None = None) -> Path:
    """Grava a cópia do dia em <pasta>/IGNF-Finora/finora-AAAA-MM-DD.db (substitui a do mesmo dia) e mantém só
    os `keep` dias mais recentes. O programa da nuvem sincroniza o arquivo."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"A pasta da nuvem não existe mais: {folder}")
    now = now or datetime.now()
    dest_dir = folder / CLOUD_SUBDIR
    made = backup_to(dest_dir / f"{CLOUD_PREFIX}{now:%Y-%m-%d}.db", db_file)
    for old in sorted(dest_dir.glob(f"{CLOUD_PREFIX}????-??-??.db"))[:-keep]:
        old.unlink()
    return made


def list_cloud(folder: Path | str) -> list[BackupInfo]:
    if not folder:
        return []
    out = []
    for p in (Path(folder) / CLOUD_SUBDIR).glob(f"{CLOUD_PREFIX}*.db"):
        try:
            out.append(inspect_backup(p))
        except ValueError:
            continue
    return sorted(out, key=lambda b: b.modified, reverse=True)
