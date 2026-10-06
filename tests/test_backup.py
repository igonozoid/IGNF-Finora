from datetime import date, datetime
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from finora.core import db
from finora.models import Base, Entry
from finora.services import accounts, backup, entries, setup
from finora.services.entries import EntryData


def _make_db(path, name="Ana", n_entries=0):
    eng = db.sqlite_pragmas(create_engine(f"sqlite:///{path}"))
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        p = setup.run_first_setup(s, name=name, currency="BRL", account_name="Banco", account_kind="bank",
                                  balance=D("100"))
        bank = accounts.list_accounts(s, p.id)[0].id
        for i in range(n_entries):
            entries.create(s, p.id, EntryData(kind="expense", description=f"E{i}", amount=D("10"),
                                              due_date=date(2026, 10, 1), account_id=bank))
    eng.dispose()
    return path


def _count_entries(path):
    eng = db.sqlite_pragmas(create_engine(f"sqlite:///{path}"))
    with Session(eng) as s:
        n = s.scalar(select(func.count(Entry.id)))
    eng.dispose()
    return n


def test_backup_e_inspecao(tmp_path):
    db_file = _make_db(tmp_path / "finora.db", n_entries=3)
    dest = backup.backup_to(tmp_path / "pendrive" / "copia.db", db_file)
    info = backup.inspect_backup(dest)
    assert (info.name, info.accounts, info.entries) == ("Ana", 1, 3)
    assert info.size > 0 and info.size_label.endswith("KB")


def test_arquivo_invalido(tmp_path):
    (tmp_path / "texto.db").write_text("não sou um banco")
    with pytest.raises(ValueError, match="não é um backup"):
        backup.inspect_backup(tmp_path / "texto.db")
    with pytest.raises(ValueError, match="não encontrado"):
        backup.inspect_backup(tmp_path / "nada.db")
    import sqlite3
    con = sqlite3.connect(tmp_path / "outro.db")
    con.execute("create table x (a)")
    con.close()
    with pytest.raises(ValueError, match="não é um backup"):
        backup.inspect_backup(tmp_path / "outro.db")


def test_restaurar_guarda_copia_do_atual(tmp_path):
    db_file = _make_db(tmp_path / "finora.db", name="Atual", n_entries=1)
    old = _make_db(tmp_path / "velho.db", name="Antigo", n_entries=5)
    safety = backup.restore_from(old, db_file, tmp_path / "backups", now=datetime(2026, 10, 2, 15, 30))
    assert _count_entries(db_file) == 5
    assert backup.inspect_backup(db_file).name == "Antigo"
    assert safety.name == "antes-de-restaurar-2026-10-02_153000.db"
    assert backup.inspect_backup(safety).name == "Atual"


def test_restaurar_arquivo_invalido_nao_mexe_no_banco(tmp_path):
    db_file = _make_db(tmp_path / "finora.db", n_entries=2)
    (tmp_path / "ruim.db").write_text("lixo")
    with pytest.raises(ValueError):
        backup.restore_from(tmp_path / "ruim.db", db_file, tmp_path / "backups")
    assert _count_entries(db_file) == 2
    assert not (tmp_path / "backups").exists()


def test_backup_automatico_um_por_dia_e_limite(tmp_path):
    db_file = _make_db(tmp_path / "finora.db")
    folder = tmp_path / "backups"
    assert backup.auto_backup(folder, db_file, now=datetime(2026, 10, 1, 9, 0)) is not None
    assert backup.auto_backup(folder, db_file, now=datetime(2026, 10, 1, 18, 0)) is None   # mesmo dia
    for day in range(2, 12):
        backup.auto_backup(folder, db_file, keep=7, now=datetime(2026, 10, day, 9, 0))
    names = sorted(p.name for p in folder.glob("auto-*.db"))
    assert len(names) == 7 and names[0] == "auto-2026-10-05_0900.db" and names[-1] == "auto-2026-10-11_0900.db"
    assert len(backup.list_local(folder)) == 7


def test_nome_sugerido():
    assert backup.suggested_name(datetime(2026, 10, 2, 9, 5)) == "finora-backup-2026-10-02_0905.db"


def test_nao_copia_sobre_o_proprio_banco(tmp_path):
    db_file = _make_db(tmp_path / "finora.db")
    with pytest.raises(ValueError):
        backup.backup_to(db_file, db_file)
    with pytest.raises(ValueError):
        backup.restore_from(db_file, db_file, tmp_path / "backups")
