"""O banco de exemplo do MCC (tests/data/mcc_exemplo.db) que o importador da Fase 2 vai usar continua íntegro,
cobre os casos combinados e bate com o gabarito. Se mudar o gerador, rode `python tools/gerar_mcc_exemplo.py`."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "tests" / "data" / "mcc_exemplo.db"
GABARITO = ROOT / "tests" / "data" / "mcc_exemplo_gabarito.json"
sys.path.insert(0, str(ROOT / "tools"))
import gerar_mcc_exemplo as gerador  # noqa: E402


@pytest.fixture
def mcc():
    db = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)
    yield db
    db.close()


def um(db, sql, *a):
    return db.execute(sql, a).fetchone()[0]


def test_banco_integro(mcc):
    assert um(mcc, "PRAGMA integrity_check") == "ok"
    assert mcc.execute("PRAGMA foreign_key_check").fetchall() == []


def test_bate_com_o_gabarito(mcc):
    assert gerador.gabarito(mcc) == json.loads(GABARITO.read_text(encoding="utf-8"))


def test_gerar_de_novo_da_o_mesmo_resultado(tmp_path):
    assert gerador.gerar(tmp_path / "mcc.db", tmp_path / "g.json") == json.loads(GABARITO.read_text(encoding="utf-8"))


def test_cobre_os_casos_do_importador(mcc):
    # compartilhados: conta e pessoa com empresa_id NULL
    assert um(mcc, "SELECT COUNT(*) FROM contas WHERE empresa_id IS NULL") == 1
    assert um(mcc, "SELECT COUNT(*) FROM pessoas WHERE empresa_id IS NULL") == 1
    # conta inativa, caixa interno e limite
    assert um(mcc, "SELECT COUNT(*) FROM contas WHERE ativa=0") == 1
    assert um(mcc, "SELECT COUNT(*) FROM contas WHERE tipo='C'") == 1
    assert um(mcc, "SELECT COUNT(*) FROM contas WHERE limite>0") == 1
    # centro só de receita (o Finora ainda não tem "aplica a receitas")
    assert um(mcc, "SELECT COUNT(*) FROM centros WHERE aplica_despesa=0 AND aplica_receita=1") == 1
    # pessoa em texto livre sem cadastro e grafia diferente da do cadastro
    assert um(mcc, "SELECT COUNT(*) FROM lancamentos WHERE pessoa='Posto Beira Rio'") == 2
    assert um(mcc, "SELECT COUNT(*) FROM lancamentos WHERE pessoa='COOPERATIVA AGRICOLA SERRA VERDE'") == 1
    # séries: mensal com centavos desiguais e quinzenal (com a última excluída)
    assert [r[0] for r in mcc.execute("SELECT valor FROM lancamentos WHERE grupo='grp-adubo-0826' ORDER BY parcela")] \
        == [1333.33, 1333.33, 1333.34]
    vencs = [r[0] for r in mcc.execute("SELECT vencimento FROM lancamentos WHERE grupo='grp-trator-quinz' "
                                       "AND excluido_em IS NULL ORDER BY parcela")]
    assert vencs == ["2026-10-01", "2026-10-16", "2026-10-31", "2026-11-15"]
    # pago sem data de pagamento, sem conta, com observação, excluídos
    assert um(mcc, "SELECT COUNT(*) FROM lancamentos WHERE situacao='V' AND data_pagamento IS NULL") == 1
    assert um(mcc, "SELECT COUNT(*) FROM lancamentos WHERE conta_id IS NULL") == 1
    assert um(mcc, "SELECT COUNT(*) FROM lancamentos WHERE observacao IS NOT NULL") == 2
    assert um(mcc, "SELECT COUNT(*) FROM lancamentos WHERE excluido_em IS NOT NULL") == 2
    # lançamento dentro do período bloqueado da empresa 1
    assert um(mcc, "SELECT COUNT(*) FROM lancamentos l JOIN empresas e ON e.id=l.empresa_id "
                   "WHERE l.data_mov <= e.bloqueio_ate") >= 1
    # movimentações: depósito, retirada, transferência realizada e prevista, excluída
    assert {r[0] for r in mcc.execute("SELECT tipo || situacao FROM movbancarias")} == {"DV", "RV", "TV", "TP"}
    assert um(mcc, "SELECT COUNT(*) FROM movbancarias WHERE excluido_em IS NOT NULL") == 1
    # usuários: admin, restrito a uma empresa, inativo; perfil do cliente em JSON; preferências e logo
    assert um(mcc, "SELECT COUNT(*) FROM usuarios WHERE admin=1") == 1
    assert um(mcc, "SELECT COUNT(*) FROM usuario_empresas") == 1
    assert um(mcc, "SELECT COUNT(*) FROM usuarios WHERE ativo=0") == 1
    assert json.loads(um(mcc, "SELECT dados FROM pessoas_extra WHERE pessoa_id=2"))["classe"] == "A"
    assert um(mcc, "SELECT valor FROM empresa_config WHERE empresa_id=1 AND chave='conta_padrao'") == "1"
    assert um(mcc, "SELECT substr(imagem, 2, 3) FROM empresa_logos") == b"PNG"


def test_senha_no_formato_do_clone(mcc):
    import hashlib
    import hmac
    alg, sal, h = um(mcc, "SELECT senha_hash FROM usuarios WHERE id=1").split("$")
    obtido = hashlib.scrypt(gerador.SENHA.encode(), salt=bytes.fromhex(sal), n=16384, r=8, p=1, dklen=64)
    assert alg == "scrypt" and hmac.compare_digest(bytes.fromhex(h), obtido)
