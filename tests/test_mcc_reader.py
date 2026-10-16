"""Leitor do banco do MCC (Fase 2.1): abre uma cópia, só para leitura, confere o formato e resume."""
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from finora.services.mcc_import import reader

DATA = Path(__file__).parent / "data"
EXEMPLO = DATA / "mcc_exemplo.db"
GABARITO = json.loads((DATA / "mcc_exemplo_gabarito.json").read_text(encoding="utf-8"))


@pytest.fixture
def mcc(tmp_path):
    p = tmp_path / "mcc.db"
    shutil.copy2(EXEMPLO, p)
    return p


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_resumo_do_banco_de_exemplo(mcc):
    before, mtime = _digest(mcc), mcc.stat().st_mtime_ns
    s = reader.read_summary(mcc)
    assert [(c.name, c.person_type, c.entries, c.deleted) for c in s.companies] == \
        [("Agro Exemplo Ltda", "PJ", 21, 2), ("João Exemplo", "PF", 5, 0)]
    agro = s.companies[0]
    assert (agro.first_day, agro.last_day, agro.document) == ("2026-02-05", "2026-10-05", "11.222.333/0001-81")
    assert s.total_entries == 26 and (s.shared_accounts, s.shared_people) == (1, 1)
    expected = {t: n for t, n in GABARITO["linhas_por_tabela"].items() if t != "sessoes"}
    assert s.rows == expected and s.missing_optional == []
    assert _digest(mcc) == before and mcc.stat().st_mtime_ns == mtime          # original intacto


def test_linhas_das_tabelas(mcc):
    with reader.open_copy(mcc) as con:
        contas = reader.rows(con, "contas")
        abertos = reader.rows(con, "lancamentos", "empresa_id=? AND situacao='P' AND excluido_em IS NULL", (1,))
        with pytest.raises(sqlite3.OperationalError):                         # cópia só para leitura
            con.execute("DELETE FROM lancamentos")
        with pytest.raises(ValueError, match="desconhecida"):
            reader.rows(con, "sqlite_master")
    assert [c["descricao"] for c in contas][:2] == ["BANCO DO BRASIL CC 12345-6", "CAIXA INTERNO"]
    assert len(abertos) == 11 and all(isinstance(r, dict) for r in abertos)   # 3 avulsos + 2 + 4 parcelas + 2 receitas


def test_le_o_que_ainda_esta_no_wal(mcc):
    """Com o MCC aberto, o que ele gravou pode estar só no arquivo -wal: a cópia leva junto."""
    live = sqlite3.connect(mcc)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("INSERT INTO empresas (id, nome, pessoa) VALUES (3, 'Nova Ltda', 'J')")
    live.commit()                                                              # fica no -wal (sem checkpoint)
    assert Path(str(mcc) + "-wal").is_file()
    try:
        assert [c.name for c in reader.read_summary(mcc).companies][-1] == "Nova Ltda"
    finally:
        live.close()


def test_clone_web_sem_as_tabelas_do_desktop(mcc):
    con = sqlite3.connect(mcc)
    for t in ("pessoas_extra", "empresa_config", "empresa_logos"):
        con.execute(f"DROP TABLE {t}")
    con.commit()
    con.close()
    s = reader.read_summary(mcc)
    assert s.missing_optional == ["pessoas_extra", "empresa_config", "empresa_logos"]
    with reader.open_copy(mcc) as c:
        assert reader.rows(c, "pessoas_extra") == []


def test_arquivos_que_nao_sao_do_mcc(tmp_path, mcc):
    with pytest.raises(reader.NotMccError, match="não encontrado"):
        reader.read_summary(tmp_path / "nada.db")
    texto = tmp_path / "texto.db"
    texto.write_text("não sou um banco")
    with pytest.raises(reader.NotMccError, match="não consegui ler"):
        reader.read_summary(texto)
    vazio = tmp_path / "vazio.db"
    sqlite3.connect(vazio).close()
    with pytest.raises(reader.NotMccError, match="faltam as tabelas"):
        reader.read_summary(vazio)
    con = sqlite3.connect(mcc)
    con.execute("ALTER TABLE lancamentos DROP COLUMN grupo")
    con.commit()
    con.close()
    with pytest.raises(reader.NotMccError, match="lancamentos não tem grupo"):
        reader.read_summary(mcc)
