"""Gera o banco de exemplo do MCC usado nos testes do importador (Fase 2 do plano de substituição do MCC).

Uso (na pasta do projeto):
    python tools/gerar_mcc_exemplo.py            # grava tests/data/mcc_exemplo.db e mcc_exemplo_gabarito.json

O banco segue o formato do clone do MCC (repositório igonozoid/MCC_CLAUDE-REA, `mcc-desktop/mcc/core/db.py`),
que é o mesmo do clone web. O esquema foi copiado para cá de propósito: o gerador não depende do clone instalado.
Todos os dados são fictícios e fixos (datas em 2026, senhas com sal derivado do e-mail), então rodar de novo dá
o mesmo conteúdo.

Cada bloco cobre um caso que o importador precisa tratar; o comentário diz qual. O gabarito traz os saldos de
cada conta calculados pela regra do MCC (`finance.saldos`), para conferir a importação.
"""
import hashlib
import json
import sqlite3
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
DB_PATH = DATA / "mcc_exemplo.db"
GABARITO_PATH = DATA / "mcc_exemplo_gabarito.json"
SENHA = "exemplo123"                      # senha de todos os usuários do exemplo
DATAS_GABARITO = ("2026-06-30", "2026-09-30", "2026-12-31")

# Cópia do esquema do clone (mcc-desktop/mcc/core/db.py), já com a coluna bloqueio_ate que ele cria na migração.
SCHEMA = """
CREATE TABLE empresas (
  id INTEGER PRIMARY KEY,
  nome TEXT NOT NULL,
  pessoa TEXT NOT NULL DEFAULT 'J' CHECK (pessoa IN ('F','J')),
  documento TEXT, documento2 TEXT,
  endereco TEXT, bairro TEXT, cidade TEXT, uf TEXT, cep TEXT,
  telefone TEXT, email TEXT, site TEXT,
  usa_centro_custo INTEGER NOT NULL DEFAULT 1,
  bloqueio_ate TEXT
);
CREATE TABLE contas (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER REFERENCES empresas(id),
  descricao TEXT NOT NULL,
  tipo TEXT NOT NULL DEFAULT 'B' CHECK (tipo IN ('B','C')),
  saldo_inicial REAL NOT NULL DEFAULT 0,
  limite REAL NOT NULL DEFAULT 0,
  ativa INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE centros (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresas(id),
  nome TEXT NOT NULL,
  aplica_despesa INTEGER NOT NULL DEFAULT 1,
  aplica_receita INTEGER NOT NULL DEFAULT 0,
  orcamento REAL NOT NULL DEFAULT 0,
  projecao REAL NOT NULL DEFAULT 0
);
CREATE TABLE pessoas (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER REFERENCES empresas(id),
  tipo TEXT NOT NULL CHECK (tipo IN ('C','F')),
  pessoa TEXT NOT NULL DEFAULT 'J' CHECK (pessoa IN ('F','J')),
  nome TEXT NOT NULL,
  documento TEXT, documento2 TEXT,
  endereco TEXT, bairro TEXT, cidade TEXT, uf TEXT, cep TEXT,
  telefone TEXT, email TEXT, contato TEXT,
  banco TEXT, agencia TEXT, conta_bancaria TEXT,
  limite REAL NOT NULL DEFAULT 0,
  observacao TEXT
);
CREATE TABLE itens (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresas(id),
  tipo TEXT NOT NULL CHECK (tipo IN ('D','R')),
  descricao TEXT NOT NULL,
  UNIQUE (empresa_id, tipo, descricao)
);
CREATE TABLE lancamentos (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresas(id),
  tipo TEXT NOT NULL CHECK (tipo IN ('D','R')),
  data_mov TEXT NOT NULL,
  documento TEXT,
  descricao TEXT NOT NULL,
  pessoa TEXT,
  valor REAL NOT NULL,
  situacao TEXT NOT NULL DEFAULT 'P' CHECK (situacao IN ('V','P')),
  vencimento TEXT NOT NULL,
  data_pagamento TEXT,
  observacao TEXT,
  conta_id INTEGER REFERENCES contas(id),
  centro_id INTEGER REFERENCES centros(id),
  grupo TEXT, parcela INTEGER, total_parcelas INTEGER,
  criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  alterado_em TEXT,
  excluido_em TEXT
);
CREATE INDEX ix_lanc ON lancamentos (empresa_id, tipo, excluido_em);
CREATE TABLE movbancarias (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresas(id),
  tipo TEXT NOT NULL CHECK (tipo IN ('D','R','T')),
  situacao TEXT NOT NULL DEFAULT 'V' CHECK (situacao IN ('V','P')),
  data TEXT NOT NULL,
  origem_id INTEGER NOT NULL REFERENCES contas(id),
  destino_id INTEGER REFERENCES contas(id),
  valor REAL NOT NULL,
  observacao TEXT,
  excluido_em TEXT
);
CREATE TABLE ofx_importados (
  conta_id INTEGER NOT NULL,
  fitid TEXT NOT NULL,
  PRIMARY KEY (conta_id, fitid)
);
CREATE TABLE usuarios (
  id INTEGER PRIMARY KEY,
  nome TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  senha_hash TEXT NOT NULL,
  admin INTEGER NOT NULL DEFAULT 0,
  ativo INTEGER NOT NULL DEFAULT 1,
  perm_config INTEGER NOT NULL DEFAULT 0 CHECK (perm_config IN (0,2)),
  perm_despesas INTEGER NOT NULL DEFAULT 2 CHECK (perm_despesas IN (0,1,2)),
  perm_receitas INTEGER NOT NULL DEFAULT 2 CHECK (perm_receitas IN (0,1,2)),
  perm_centros INTEGER NOT NULL DEFAULT 2 CHECK (perm_centros IN (0,1,2)),
  perm_bancos INTEGER NOT NULL DEFAULT 2 CHECK (perm_bancos IN (0,1,2)),
  perm_fluxo INTEGER NOT NULL DEFAULT 2 CHECK (perm_fluxo IN (0,1,2)),
  todas_empresas INTEGER NOT NULL DEFAULT 1,
  criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  ultimo_acesso TEXT
);
CREATE TABLE usuario_empresas (
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  PRIMARY KEY (usuario_id, empresa_id)
);
CREATE TABLE sessoes (
  token TEXT PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  expira_em INTEGER NOT NULL
);
CREATE TABLE pessoas_extra (
  pessoa_id INTEGER PRIMARY KEY REFERENCES pessoas(id) ON DELETE CASCADE,
  dados TEXT NOT NULL DEFAULT '{}',
  criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE empresa_config (
  empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
  chave TEXT NOT NULL,
  valor TEXT,
  PRIMARY KEY (empresa_id, chave)
);
CREATE TABLE empresa_logos (
  empresa_id INTEGER PRIMARY KEY REFERENCES empresas(id) ON DELETE CASCADE,
  imagem BLOB NOT NULL
);
"""

CRIADO = "2026-01-02 09:00:00"


def hash_senha(senha: str, email: str) -> str:
    """Mesmo formato do clone (scrypt N=16384, r=8, p=1, 64 bytes), com sal fixo para o arquivo não mudar."""
    sal = hashlib.sha256(email.encode()).digest()[:16]
    h = hashlib.scrypt(senha.encode(), salt=sal, n=16384, r=8, p=1, dklen=64)
    return f"scrypt${sal.hex()}${h.hex()}"


def png_1px(r: int, g: int, b: int) -> bytes:
    """PNG de 1×1 pixel, sem depender do Qt."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes([0, r, g, b])))
            + chunk(b"IEND", b""))


def inserir(db: sqlite3.Connection, tabela: str, linhas: list[dict]) -> None:
    for linha in linhas:
        cols = ", ".join(linha)
        db.execute(f"INSERT INTO {tabela} ({cols}) VALUES ({', '.join('?' * len(linha))})", tuple(linha.values()))


def lanc(id_, emp, tipo, data_mov, descricao, valor, vencimento, *, situacao="P", pgto=None, doc=None, pessoa=None,
         obs=None, conta=None, centro=None, grupo=None, parcela=None, total=None, excluido=None) -> dict:
    return {"id": id_, "empresa_id": emp, "tipo": tipo, "data_mov": data_mov, "documento": doc, "descricao": descricao,
            "pessoa": pessoa, "valor": valor, "situacao": situacao, "vencimento": vencimento, "data_pagamento": pgto,
            "observacao": obs, "conta_id": conta, "centro_id": centro, "grupo": grupo, "parcela": parcela,
            "total_parcelas": total, "criado_em": CRIADO, "excluido_em": excluido}


def popular(db: sqlite3.Connection) -> None:
    # --- Contas controle: uma PJ com período bloqueado e centros de custo; uma PF que não usa centro de custo.
    inserir(db, "empresas", [
        {"id": 1, "nome": "Agro Exemplo Ltda", "pessoa": "J", "documento": "11.222.333/0001-81",
         "documento2": "123.456.789.110", "endereco": "Estrada Velha, km 12", "bairro": "Zona Rural",
         "cidade": "Maria da Fé", "uf": "MG", "cep": "37517-000", "telefone": "(35) 3662-0000",
         "email": "contato@agroexemplo.test", "site": "agroexemplo.test", "usa_centro_custo": 1,
         "bloqueio_ate": "2026-03-31"},
        {"id": 2, "nome": "João Exemplo", "pessoa": "F", "documento": "529.982.247-25", "documento2": "MG-12.345.678",
         "endereco": "Rua das Flores, 100", "bairro": "Centro", "cidade": "Itajubá", "uf": "MG", "cep": "37500-000",
         "email": "joao@exemplo.test", "usa_centro_custo": 0},
    ])
    db.execute("INSERT INTO empresa_logos (empresa_id, imagem) VALUES (1, ?)", (png_1px(224, 154, 10),))
    # Preferências do FConfigConta: a empresa 2 fica sem registro (usa os padrões do MCC).
    inserir(db, "empresa_config", [
        {"empresa_id": 1, "chave": k, "valor": v}
        for k, v in {"exibir_saldos": "1", "itens_proprios": "0", "campo_inicial": "documento",
                     "conta_padrao": "1"}.items()])

    # --- Contas: banco com limite, caixa interno, compartilhada (empresa_id NULL), da PF e uma inativa.
    inserir(db, "contas", [
        {"id": 1, "empresa_id": 1, "descricao": "BANCO DO BRASIL CC 12345-6", "tipo": "B", "saldo_inicial": 10000.0,
         "limite": 5000.0, "ativa": 1},
        {"id": 2, "empresa_id": 1, "descricao": "CAIXA INTERNO", "tipo": "C", "saldo_inicial": 500.0, "limite": 0,
         "ativa": 1},
        {"id": 3, "empresa_id": None, "descricao": "ITAÚ COMPARTILHADA 9876-5", "tipo": "B", "saldo_inicial": 2500.5,
         "limite": 0, "ativa": 1},
        {"id": 4, "empresa_id": 2, "descricao": "NUBANK PF", "tipo": "B", "saldo_inicial": 1200.0, "limite": 0,
         "ativa": 1},
        {"id": 5, "empresa_id": 1, "descricao": "CONTA ANTIGA (ENCERRADA)", "tipo": "B", "saldo_inicial": 0,
         "limite": 0, "ativa": 0},
    ])

    # --- Centros: só despesa, despesa e receita, só receita.
    inserir(db, "centros", [
        {"id": 1, "empresa_id": 1, "nome": "Administrativo", "aplica_despesa": 1, "aplica_receita": 0,
         "orcamento": 3000.0, "projecao": 0},
        {"id": 2, "empresa_id": 1, "nome": "Lavoura de oliveiras", "aplica_despesa": 1, "aplica_receita": 1,
         "orcamento": 8000.0, "projecao": 15000.0},
        {"id": 3, "empresa_id": 1, "nome": "Vendas", "aplica_despesa": 0, "aplica_receita": 1, "orcamento": 0,
         "projecao": 20000.0},
        {"id": 4, "empresa_id": 2, "nome": "Casa", "aplica_despesa": 1, "aplica_receita": 0, "orcamento": 2500.0,
         "projecao": 0},
    ])

    # --- Pessoas: fornecedor PJ, cliente PJ com perfil completo, cliente PF com RG, compartilhada, da PF.
    pessoa = {"documento": None, "documento2": None, "endereco": None, "bairro": None, "cidade": None, "uf": None,
              "cep": None, "telefone": None, "email": None, "contato": None, "banco": None, "agencia": None,
              "conta_bancaria": None, "limite": 0, "observacao": None}
    inserir(db, "pessoas", [
        {**pessoa, "id": 1, "empresa_id": 1, "tipo": "F", "pessoa": "J", "nome": "Insumos Agrícolas do Sul Ltda",
         "documento": "04.252.011/0001-10", "cidade": "Pouso Alegre", "uf": "MG", "telefone": "(35) 3421-0000",
         "contato": "Carlos (vendas)", "banco": "341 - Itaú", "agencia": "0123", "conta_bancaria": "45678-9"},
        {**pessoa, "id": 2, "empresa_id": 1, "tipo": "C", "pessoa": "J", "nome": "Cooperativa Agrícola Serra Verde",
         "documento": "45.723.174/0001-10", "documento2": "987.654.321.000", "endereco": "Av. Brasil, 2000",
         "bairro": "Industrial", "cidade": "Varginha", "uf": "MG", "cep": "37010-000", "email": "compras@coop.test",
         "contato": "Ana", "limite": 50000.0, "observacao": "Paga sempre no 2º dia útil."},
        {**pessoa, "id": 3, "empresa_id": 1, "tipo": "C", "pessoa": "F", "nome": "Maria Cliente",
         "documento": "111.444.777-35", "documento2": "MG-98.765.432", "telefone": "(35) 99999-0000"},
        {**pessoa, "id": 4, "empresa_id": None, "tipo": "F", "pessoa": "J", "nome": "Energia Compartilhada S.A.",
         "documento": "33.000.167/0001-01"},
        {**pessoa, "id": 5, "empresa_id": 2, "tipo": "F", "pessoa": "J", "nome": "Supermercado Bom Preço"},
    ])
    inserir(db, "pessoas_extra", [{
        "pessoa_id": 2, "criado_em": CRIADO,
        "dados": json.dumps({
            "contato_financeiro": "Ana Souza", "contato_administrativo": "Pedro Lima", "contato_tecnico": "",
            "fundacao": "15/03/1998",
            "ref_comercial1": "Agropecuária Boa Safra", "ref_comercial1_tel": "(35) 3333-1111",
            "ref_comercial2": "Distribuidora Minas", "ref_comercial2_tel": "(35) 3333-2222",
            "ref_banco": "001 - Banco do Brasil", "ref_agencia": "4321", "ref_conta": "11111-1",
            "ref_telefone": "(35) 3333-3333", "data_consulta": "10/01/2026", "local_pendencia": "", "nome_mae": "",
            "titular": "Cooperativa Agrícola Serra Verde", "pix": "45.723.174/0001-10",
            "frequencia": "M", "classe": "A", "credito_consultado": "S", "pendencia": "N",
        }, ensure_ascii=False)}])

    # --- Itens de despesa e receita (lista plana, sem grupo da DRE).
    itens = {1: {"D": ["Adubos e fertilizantes", "Combustível", "Energia elétrica", "Salários", "Tarifas bancárias",
                       "Manutenção de máquinas"],
                 "R": ["Venda de azeite", "Venda de mel", "Prestação de serviços"]},
             2: {"D": ["Supermercado", "Aluguel"], "R": ["Salário"]}}
    n = 0
    for emp, por_tipo in itens.items():
        for tipo, nomes in por_tipo.items():
            for nome in nomes:
                n += 1
                inserir(db, "itens", [{"id": n, "empresa_id": emp, "tipo": tipo, "descricao": nome}])

    L = []
    # Empresa 1 — despesas pagas em contas diferentes, com e sem centro de custo.
    L += [lanc(1, 1, "D", "2026-02-05", "Energia elétrica", 412.37, "2026-02-10", situacao="V", pgto="2026-02-10",
               doc="FAT-0226", pessoa="Energia Compartilhada S.A.", conta=1, centro=1),  # antes do bloqueio
          lanc(2, 1, "D", "2026-05-05", "Energia elétrica", 398.9, "2026-05-10", situacao="V", pgto="2026-05-12",
               doc="FAT-0526", pessoa="ENERGIA COMPARTILHADA S.A.", conta=1, centro=1),   # nome em maiúsculas
          lanc(3, 1, "D", "2026-05-20", "Combustível", 350.0, "2026-05-20", situacao="V", pgto="2026-05-20",
               pessoa="Posto Beira Rio", conta=2, centro=2),                             # pessoa sem cadastro
          lanc(4, 1, "D", "2026-06-30", "Tarifas bancárias", 89.9, "2026-06-30", situacao="V", pgto="2026-06-30",
               conta=1),                                                                 # sem pessoa e sem centro
          lanc(5, 1, "D", "2026-07-01", "Salários", 3200.0, "2026-07-05", situacao="V", pgto="2026-07-05",
               pessoa="Folha de julho", conta=3, centro=1),                              # paga pela conta compartilhada
          # Baixa com valor diferente do previsto (juros): no MCC o valor é sobrescrito; a obs. conta o motivo.
          lanc(6, 1, "D", "2026-07-10", "Manutenção de máquinas", 1050.0, "2026-07-20", situacao="V",
               pgto="2026-07-25", doc="OS-778", pessoa="Insumos Agrícolas do Sul Ltda",
               obs="Pago com 5 dias de atraso: R$ 1.000,00 + R$ 50,00 de juros", conta=1, centro=2),
          # Situação "V" sem data de pagamento (dado antigo): os relatórios do MCC usam o vencimento no lugar, mas
          # o saldo das contas (finance.saldos) NÃO conta esse lançamento. O importador precisa escolher.
          lanc(7, 1, "D", "2026-04-02", "Combustível", 120.0, "2026-04-02", situacao="V", pgto=None, conta=2,
               centro=2),
          # Em aberto: vencida, a vencer, e sem conta definida.
          lanc(8, 1, "D", "2026-09-01", "Energia elétrica", 405.15, "2026-09-10", doc="FAT-0926",
               pessoa="Energia Compartilhada S.A.", conta=1, centro=1),
          lanc(9, 1, "D", "2026-10-01", "Manutenção de máquinas", 780.0, "2026-11-15",
               pessoa="Insumos Agrícolas do Sul Ltda", conta=1, centro=2),
          lanc(10, 1, "D", "2026-10-05", "Combustível", 260.0, "2026-10-30", pessoa="Posto Beira Rio")]
    # Parcelamento mensal 3x com centavos que não dividem (33,33 + 33,33 + 33,34 por mil): 1ª paga, 2 em aberto.
    for i, (valor, ven, sit, pg) in enumerate([(1333.33, "2026-08-10", "V", "2026-08-10"),
                                                (1333.33, "2026-09-10", "P", None),
                                                (1333.34, "2026-10-10", "P", None)], start=1):
        L.append(lanc(10 + i, 1, "D", "2026-08-01", "Adubos e fertilizantes", valor, ven, situacao=sit, pgto=pg,
                      doc=f"NF-4521 {i}/3", pessoa="Insumos Agrícolas do Sul Ltda", conta=1, centro=2,
                      grupo="grp-adubo-0826", parcela=i, total=3))
    # Parcelamento quinzenal 5x (periodicidade que o Finora ainda não tem), em aberto; a 5ª foi excluída (abaixo).
    for i, ven in enumerate(["2026-10-01", "2026-10-16", "2026-10-31", "2026-11-15"], start=1):
        L.append(lanc(13 + i, 1, "D", "2026-09-25", "Manutenção de máquinas", 250.0, ven, doc=f"{i}/5",
                      pessoa="Insumos Agrícolas do Sul Ltda", conta=1, centro=2, grupo="grp-trator-quinz",
                      parcela=i, total=5))
    # Receitas: pagas (com nome do cliente em grafia diferente do cadastro) e a receber.
    L += [lanc(18, 1, "R", "2026-06-15", "Venda de azeite", 8750.0, "2026-06-30", situacao="V", pgto="2026-07-02",
               doc="NFE-1001", pessoa="COOPERATIVA AGRICOLA SERRA VERDE", obs="Pagou com 2 dias de atraso",
               conta=1, centro=3),
          lanc(19, 1, "R", "2026-07-20", "Venda de mel", 1240.5, "2026-07-20", situacao="V", pgto="2026-07-20",
               pessoa="Maria Cliente", conta=2, centro=2),
          lanc(20, 1, "R", "2026-09-15", "Venda de azeite", 12300.0, "2026-10-15", doc="NFE-1002",
               pessoa="Cooperativa Agrícola Serra Verde", conta=1, centro=3),
          lanc(21, 1, "R", "2026-09-20", "Prestação de serviços", 600.0, "2026-09-25", pessoa="Maria Cliente",
               conta=2)]                                                                 # a receber vencida
    # Excluídos (vão para a lixeira do Finora): um avulso e um de série.
    L += [lanc(22, 1, "D", "2026-06-10", "Combustível", 99.99, "2026-06-10", situacao="V", pgto="2026-06-10",
               conta=2, excluido="2026-06-11 08:30:00"),
          lanc(23, 1, "D", "2026-09-25", "Manutenção de máquinas", 250.0, "2026-11-30", doc="5/5",
               pessoa="Insumos Agrícolas do Sul Ltda", conta=1, centro=2, grupo="grp-trator-quinz", parcela=5,
               total=5, excluido="2026-09-26 10:00:00")]
    # Empresa 2 (PF, sem centro de custo).
    L += [lanc(24, 2, "R", "2026-07-05", "Salário", 7500.0, "2026-07-05", situacao="V", pgto="2026-07-05", conta=4),
          lanc(25, 2, "D", "2026-07-08", "Supermercado", 845.62, "2026-07-08", situacao="V", pgto="2026-07-08",
               pessoa="Supermercado Bom Preço", conta=4, centro=4),
          lanc(26, 2, "D", "2026-07-10", "Aluguel", 2100.0, "2026-07-10", situacao="V", pgto="2026-07-10",
               pessoa="Imobiliária Central", conta=4),
          lanc(27, 2, "D", "2026-10-10", "Aluguel", 2100.0, "2026-10-10", pessoa="Imobiliária Central", conta=4),
          lanc(28, 2, "D", "2026-08-02", "Energia elétrica", 210.4, "2026-08-10", situacao="V", pgto="2026-08-10",
               pessoa="Energia Compartilhada S.A.", conta=3)]                            # PF usando a compartilhada
    inserir(db, "lancamentos", L)

    # --- Movimentações bancárias: depósito, retirada, transferência realizada e prevista, excluída.
    inserir(db, "movbancarias", [
        {"id": 1, "empresa_id": 1, "tipo": "D", "situacao": "V", "data": "2026-05-02", "origem_id": 2,
         "destino_id": None, "valor": 1500.0, "observacao": "Aporte dos sócios em dinheiro"},
        {"id": 2, "empresa_id": 1, "tipo": "R", "situacao": "V", "data": "2026-06-05", "origem_id": 1,
         "destino_id": None, "valor": 300.0, "observacao": "Saque para despesas miúdas"},
        {"id": 3, "empresa_id": 1, "tipo": "T", "situacao": "V", "data": "2026-06-05", "origem_id": 1,
         "destino_id": 2, "valor": 700.0, "observacao": "Reforço do caixa"},
        {"id": 4, "empresa_id": 1, "tipo": "T", "situacao": "P", "data": "2026-10-20", "origem_id": 1,
         "destino_id": 3, "valor": 2000.0, "observacao": "Transferência programada"},
        {"id": 5, "empresa_id": 1, "tipo": "R", "situacao": "V", "data": "2026-07-01", "origem_id": 2,
         "destino_id": None, "valor": 50.0, "observacao": "Lançada errado", "excluido_em": "2026-07-02 09:00:00"},
        {"id": 6, "empresa_id": 2, "tipo": "T", "situacao": "V", "data": "2026-07-06", "origem_id": 4,
         "destino_id": 3, "valor": 1000.0, "observacao": None},
    ])
    inserir(db, "ofx_importados", [{"conta_id": 1, "fitid": "202606300001"}, {"conta_id": 1, "fitid": "202606300002"}])

    # --- Usuários: administrador, operador restrito à empresa 1 e um inativo. Senha de todos: SENHA.
    usuario = {"admin": 0, "ativo": 1, "perm_config": 0, "perm_despesas": 2, "perm_receitas": 2, "perm_centros": 2,
               "perm_bancos": 2, "perm_fluxo": 2, "todas_empresas": 1, "criado_em": CRIADO, "ultimo_acesso": None}
    inserir(db, "usuarios", [
        {**usuario, "id": 1, "nome": "Administrador", "email": "admin@exemplo.test", "admin": 1, "perm_config": 2,
         "senha_hash": hash_senha(SENHA, "admin@exemplo.test"), "ultimo_acesso": "2026-10-14 17:45:00"},
        {**usuario, "id": 2, "nome": "Operador Financeiro", "email": "operador@exemplo.test", "perm_receitas": 1,
         "perm_centros": 0, "perm_bancos": 1, "perm_fluxo": 0, "todas_empresas": 0,
         "senha_hash": hash_senha(SENHA, "operador@exemplo.test")},
        {**usuario, "id": 3, "nome": "Ex-funcionário", "email": "antigo@exemplo.test", "ativo": 0,
         "senha_hash": hash_senha(SENHA, "antigo@exemplo.test")},
    ])
    inserir(db, "usuario_empresas", [{"usuario_id": 2, "empresa_id": 1}])


def saldos(db: sqlite3.Connection, ate: str) -> dict[str, dict[str, float]]:
    """Saldo realizado e previsto de cada conta numa data: a mesma conta de `finance.saldos` do clone, que soma os
    lançamentos de todas as empresas na conta (compartilhada inclusive) e as movimentações bancárias."""
    out = {}
    for c in db.execute("SELECT id, descricao, saldo_inicial FROM contas ORDER BY id"):
        l = db.execute("""SELECT
            COALESCE(SUM(CASE WHEN situacao='V' AND data_pagamento<=? THEN (CASE tipo WHEN 'R' THEN valor ELSE -valor END) END),0),
            COALESCE(SUM(CASE WHEN (situacao='V' AND data_pagamento<=?) OR (situacao='P' AND vencimento<=?)
                THEN (CASE tipo WHEN 'R' THEN valor ELSE -valor END) END),0)
            FROM lancamentos WHERE conta_id=? AND excluido_em IS NULL""", (ate, ate, ate, c[0])).fetchone()
        m = db.execute("""SELECT COALESCE(SUM(CASE WHEN situacao='V' THEN v END),0), COALESCE(SUM(v),0) FROM (
              SELECT situacao, CASE tipo WHEN 'D' THEN valor ELSE -valor END AS v FROM movbancarias
                WHERE origem_id=? AND data<=? AND excluido_em IS NULL
              UNION ALL
              SELECT situacao, valor FROM movbancarias WHERE tipo='T' AND destino_id=? AND data<=? AND excluido_em IS NULL)""",
                       (c[0], ate, c[0], ate)).fetchone()
        out[str(c[0])] = {"descricao": c[1], "realizado": round(c[2] + l[0] + m[0], 2),
                          "previsto": round(c[2] + l[1] + m[1], 2)}
    return out


def gabarito(db: sqlite3.Connection) -> dict:
    def um(sql: str, *a):
        return db.execute(sql, a).fetchone()[0]
    tabelas = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    por_empresa = {}
    for (emp,) in db.execute("SELECT id FROM empresas ORDER BY id"):
        base = "FROM lancamentos WHERE empresa_id=? AND excluido_em IS NULL"
        por_empresa[str(emp)] = {
            "lancamentos_ativos": um(f"SELECT COUNT(*) {base}", emp),
            "lancamentos_excluidos": um("SELECT COUNT(*) FROM lancamentos WHERE empresa_id=? AND excluido_em IS NOT NULL", emp),
            "a_pagar": round(um(f"SELECT COALESCE(SUM(valor),0) {base} AND tipo='D' AND situacao='P'", emp), 2),
            "a_receber": round(um(f"SELECT COALESCE(SUM(valor),0) {base} AND tipo='R' AND situacao='P'", emp), 2),
            "pago": round(um(f"SELECT COALESCE(SUM(valor),0) {base} AND tipo='D' AND situacao='V'", emp), 2),
            "recebido": round(um(f"SELECT COALESCE(SUM(valor),0) {base} AND tipo='R' AND situacao='V'", emp), 2),
            "pessoas_distintas_nos_lancamentos": um(
                f"SELECT COUNT(DISTINCT pessoa) {base} AND pessoa IS NOT NULL", emp),
        }
    return {
        "senha_dos_usuarios": SENHA,
        "linhas_por_tabela": {t: um(f"SELECT COUNT(*) FROM {t}") for t in tabelas},
        "por_empresa": por_empresa,
        "saldos": {d: saldos(db, d) for d in DATAS_GABARITO},
    }


def gerar(db_path: Path = DB_PATH, gabarito_path: Path = GABARITO_PATH) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)
        with db:
            popular(db)
        g = gabarito(db)
        db.execute("VACUUM")
    finally:
        db.close()
    gabarito_path.write_text(json.dumps(g, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return g


if __name__ == "__main__":
    g = gerar()
    print(f"Gerado {DB_PATH.relative_to(ROOT)} e {GABARITO_PATH.relative_to(ROOT)}")
    for tabela, n in g["linhas_por_tabela"].items():
        print(f"  {tabela:18} {n}")
    sys.exit(0)
