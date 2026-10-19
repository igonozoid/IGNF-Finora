"""Planilhas exportadas do MCC original (Fase 2.10 · 2B): perfis de coluna e montagem de um banco no formato do
clone (mcc.db), para seguir o mesmo caminho da importação e da conferência (mapper, conference).

O MCC original exporta CSV em Latin-1, separado por ";", com título, período e uma linha em branco (espaço do logo)
antes das colunas e uma linha de totais no fim. O que cada relatório traz (docs/PLANO-MCC.md, issue #5):
- Relatório Analítico (despesas e receitas): os lançamentos, sem a data de pagamento;
- Saldo de contas: o saldo inicial de cada conta;
- Extratos (banco e caixa): os pagos/recebidos na data do pagamento, as transferências e o saldo final no rodapé;
- Clientes / Fornecedores: os cadastros (um registro por lançamento: repetem o nome).
A data de pagamento sai do extrato; transferência só entra quando os dois lados aparecem (saída numa conta e
entrada na outra, mesma data e valor) — o que tem um lado só fica de fora, como no saldo do próprio MCC.
Parcelas (série) não vêm na planilha: ficam soltas (agrupar é a Fase 2.12).
"""
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from finora.services.statement_import import parse_amount, parse_date

ZERO = Decimal("0.00")


def _key(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).upper().split())


# perfil -> colunas que identificam o relatório (sem acento, maiúsculas)
PROFILES = {
    "analitico": {"DATA", "DOCUMENTO", "DESCRICAO", "NOME", "VALOR", "MOVSIT", "VENCIMENTO", "OBSERVACAO", "CONTA",
                  "CENTRO DE CUSTO", "TIPO"},
    "extrato": {"DATA", "MOV", "NOME", "TIPO", "OBS", "CREDITO", "DEBITO"},
    "contas": {"CONTA"},                                   # + "SALDO EM dd/mm/aaaa"
    "cadastro": {"DOCUMENTO", "NOME", "ENDERECO", "BAIRRO", "CIDADE", "ESTADO", "CEP", "TELEFONE", "E-MAIL"},
    "a_pagar_receber": {"DATA MOVIMENTO", "DOCUMENTO", "DESCRICAO", "NOME", "VALOR", "VENCIMENTO", "OBSERVACAO"},
    "centros": {"CENTRO DE CUSTO"},
}
DATED = {"analitico", "extrato", "a_pagar_receber"}
KEY_COLUMN = {"contas": "CONTA", "cadastro": "NOME", "centros": "CENTRO DE CUSTO"}
LABELS = {"analitico": "Relatório Analítico", "extrato": "Extrato", "contas": "Saldo de contas",
          "cadastro": "Clientes / Fornecedores", "a_pagar_receber": "Contas a pagar / a receber",
          "centros": "Centros de custo"}
_DATE = re.compile(r"^\d\d/\d\d/\d{4}$")
_FOOT = re.compile(r"(?:Conta:\s*(?P<conta>.+?)\s+-\s+|(?P<caixa>Caixa Interno):\s*)Saldo até [\d/]+:\s*(?P<ini>R\$-?\s*-?[\d.,]+)"
                   r"\s+Saldo final em [\d/]+:\s*(?P<fim>R\$-?\s*-?[\d.,]+)", re.I)


@dataclass
class Sheet:
    path: Path
    kind: str                                  # perfil (PROFILES) ou "" se não reconheceu
    title: str
    header: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)          # coluna (sem acento) -> texto
    account: str = ""                          # extrato: a conta do rodapé
    cash: bool = False                         # extrato do caixa interno
    opening: Decimal | None = None             # extrato: saldo anterior (rodapé)
    final: Decimal | None = None               # extrato: saldo final (rodapé)

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, "Não reconhecido")


def _profile(cells: list[str]) -> str:
    keys = {_key(c) for c in cells if c.strip()}
    if not keys:
        return ""
    for kind in ("analitico", "extrato", "a_pagar_receber", "cadastro"):
        if PROFILES[kind] <= keys:
            return kind
    if "CONTA" in keys and any(k.startswith("SALDO EM") for k in keys) and len(keys) == 2:
        return "contas"
    if "CENTRO DE CUSTO" in keys and "VALOR" not in keys:
        return "centros"
    return ""


def read_sheet(path: str | Path) -> Sheet:
    """Lê um CSV exportado pelo MCC: acha a linha das colunas (pulando título e espaço do logo), junta observação
    que quebrou de linha e separa o rodapé."""
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    lines = text.lstrip("﻿").splitlines()
    title = lines[0].strip(" ;") if lines else ""
    head_at, kind = -1, ""
    for i, line in enumerate(lines[:15]):
        kind = _profile(line.split(";"))
        if kind:
            head_at = i
            break
    sheet = Sheet(path, kind, title)
    if head_at < 0:
        return sheet
    header = [_key(h) for h in lines[head_at].rstrip().rstrip(";").split(";")]
    sheet.header = header
    raw_rows: list[str] = []
    for line in lines[head_at + 1:]:
        cells = line.split(";")
        first = cells[0].strip()
        if _key(first) == header[0] and kind == "contas":     # o relatório de saldos repete o bloco
            break
        m = _FOOT.search(line)
        if m:
            sheet.account = (m.group("conta") or m.group("caixa") or "").strip()
            sheet.cash = bool(m.group("caixa"))
            sheet.opening, sheet.final = parse_amount(m.group("ini")), parse_amount(m.group("fim"))
            continue
        if kind in DATED:
            if _DATE.match(first):
                raw_rows.append(line)
            elif raw_rows and line.strip(" ;") and not line.startswith(";"):
                raw_rows[-1] = raw_rows[-1].rstrip() + "\n" + line.strip()   # observação com quebra de linha
            continue
        if not line.strip(" ;"):
            continue
        if not first and len(cells) > 1 and not cells[1].strip():      # linha de totais
            continue
        raw_rows.append(line)
    must = KEY_COLUMN.get(kind)                          # sem ela, é linha de totais ou em branco
    for line in raw_rows:
        cells = [c.strip() for c in line.rstrip().rstrip(";").split(";")]
        cells += [""] * (len(header) - len(cells))
        row = dict(zip(header, cells))
        if must is None or row.get(must):
            sheet.rows.append(row)
    if kind == "extrato" and not sheet.account and "caixa" in title.lower():
        sheet.cash = True
    return sheet


# ---------- conjunto de planilhas -> banco no formato do MCC ----------
@dataclass
class BalanceCheck:
    account: str
    expected: Decimal                          # saldo final do rodapé do extrato (o do MCC)
    rebuilt: Decimal                           # saldo inicial + pagos/recebidos + transferências montados aqui

    @property
    def ok(self) -> bool:
        return self.expected == self.rebuilt


@dataclass
class Bundle:
    sheets: list[Sheet]
    entries: int = 0
    paid_dates_found: int = 0
    paid_dates_missing: int = 0
    transfers: int = 0
    left_out: list[str] = field(default_factory=list)       # movimentações de um lado só (fora)
    balances: list[BalanceCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def of(self, kind: str) -> list[Sheet]:
        return [s for s in self.sheets if s.kind == kind]


SCHEMA = """
CREATE TABLE empresas (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, pessoa TEXT NOT NULL, documento TEXT,
  endereco TEXT, bairro TEXT, cidade TEXT, uf TEXT, cep TEXT, telefone TEXT, email TEXT,
  usa_centro_custo INTEGER NOT NULL DEFAULT 1, bloqueio_ate TEXT);
CREATE TABLE contas (id INTEGER PRIMARY KEY, empresa_id INTEGER, descricao TEXT NOT NULL, tipo TEXT NOT NULL,
  saldo_inicial REAL NOT NULL DEFAULT 0, limite REAL NOT NULL DEFAULT 0, ativa INTEGER NOT NULL DEFAULT 1);
CREATE TABLE centros (id INTEGER PRIMARY KEY, empresa_id INTEGER NOT NULL, nome TEXT NOT NULL,
  aplica_despesa INTEGER NOT NULL, aplica_receita INTEGER NOT NULL, orcamento REAL NOT NULL DEFAULT 0,
  projecao REAL NOT NULL DEFAULT 0);
CREATE TABLE pessoas (id INTEGER PRIMARY KEY, empresa_id INTEGER, tipo TEXT NOT NULL, pessoa TEXT NOT NULL,
  nome TEXT NOT NULL, documento TEXT, documento2 TEXT, endereco TEXT, bairro TEXT, cidade TEXT, uf TEXT, cep TEXT,
  telefone TEXT, email TEXT, contato TEXT, banco TEXT, agencia TEXT, conta_bancaria TEXT,
  limite REAL NOT NULL DEFAULT 0, observacao TEXT);
CREATE TABLE itens (id INTEGER PRIMARY KEY, empresa_id INTEGER NOT NULL, tipo TEXT NOT NULL, descricao TEXT NOT NULL,
  UNIQUE (empresa_id, tipo, descricao));
CREATE TABLE lancamentos (id INTEGER PRIMARY KEY, empresa_id INTEGER NOT NULL, tipo TEXT NOT NULL,
  data_mov TEXT NOT NULL, documento TEXT, descricao TEXT NOT NULL, pessoa TEXT, valor REAL NOT NULL,
  situacao TEXT NOT NULL, vencimento TEXT NOT NULL, data_pagamento TEXT, observacao TEXT, conta_id INTEGER,
  centro_id INTEGER, grupo TEXT, parcela INTEGER, total_parcelas INTEGER, criado_em TEXT NOT NULL,
  alterado_em TEXT, excluido_em TEXT);
CREATE TABLE movbancarias (id INTEGER PRIMARY KEY, empresa_id INTEGER NOT NULL, tipo TEXT NOT NULL,
  situacao TEXT NOT NULL DEFAULT 'V', data TEXT NOT NULL, origem_id INTEGER NOT NULL, destino_id INTEGER,
  valor REAL NOT NULL, observacao TEXT, excluido_em TEXT);
CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, email TEXT NOT NULL, senha_hash TEXT NOT NULL,
  admin INTEGER NOT NULL DEFAULT 0, ativo INTEGER NOT NULL DEFAULT 1);
"""


def _iso(text: str) -> str | None:
    d = parse_date(text)
    return d.isoformat() if d else None


def _money(text: str) -> Decimal:
    return parse_amount(text) or ZERO


def load(paths: list[str | Path]) -> Bundle:
    """Lê os CSV escolhidos. Os que não são de um relatório conhecido viram aviso (e ficam de fora)."""
    sheets = [read_sheet(p) for p in paths if str(p).lower().endswith(".csv")]
    b = Bundle(sheets)
    for s in sheets:
        if not s.kind:
            b.warnings.append(f"{s.path.name}: não reconheci esse relatório do MCC; ficou de fora.")
    if not b.of("analitico"):
        raise ValueError("Falta o Relatório Analítico (despesas e receitas) em CSV: é dele que vêm os lançamentos.")
    return b


def _person(doc: str) -> str:
    d = re.sub(r"\D", "", doc or "")
    return "J" if len(d) == 14 else "F"


def _people(b: Bundle) -> list[dict]:
    """Clientes e fornecedores sem repetição: por nome, ficando com o registro mais completo (o com documento)."""
    best: dict[tuple[str, str], dict] = {}
    for s in b.of("cadastro"):
        tipo = "C" if "CLIENTE" in _key(s.title) else "F"
        for r in s.rows:
            name = (r.get("NOME") or "").strip()
            if not name:
                continue
            k = (tipo, _key(name))
            score = (bool(r.get("DOCUMENTO")), sum(bool(v) for v in r.values()))
            if k not in best or score > best[k][0]:
                best[k] = (score, r)
    return [dict(r, _tipo=tipo) for (tipo, _k), (_s, r) in best.items()]


def build_db(b: Bundle, dest: str | Path, *, company: str, person_type: str = "PJ", document: str = "") -> Path:
    """Monta `dest` (SQLite no formato do clone do MCC) a partir das planilhas. Preenche os avisos e a conferência
    dos saldos com o rodapé dos extratos em `b`."""
    dest = Path(dest)
    if dest.exists():
        dest.unlink()
    con = sqlite3.connect(dest)
    try:
        con.executescript(SCHEMA)
        con.execute("INSERT INTO empresas (id, nome, pessoa, documento) VALUES (1, ?, ?, ?)",
                    (company.strip(), "J" if person_type == "PJ" else "F", re.sub(r"\D", "", document) or None))
        entries = [r for s in b.of("analitico") for r in s.rows]
        b.entries = len(entries)

        # contas: saldo inicial do relatório de saldos; o tipo (caixa) vem do extrato
        opening = {}
        for s in b.of("contas"):
            col = next((c for c in s.header if c.startswith("SALDO EM")), None)
            for r in s.rows:
                if r.get("CONTA"):
                    opening[r["CONTA"]] = _money(r.get(col, ""))
        cash = {s.account for s in b.of("extrato") if s.cash}
        names = list(opening) + sorted({r["CONTA"] for r in entries if r.get("CONTA")} - set(opening))
        if not b.of("contas"):
            b.warnings.append("Sem o relatório de saldo de contas: os saldos iniciais ficaram zerados.")
        acc_id = {}
        for i, name in enumerate(names, start=1):
            is_cash = name in cash or "CAIXA" in _key(name)
            ext = next((s for s in b.of("extrato") if _key(s.account) in (_key(name), "CAIXA INTERNO" if is_cash else "")),
                       None)
            start = opening.get(name, ext.opening if ext and ext.opening is not None else ZERO)
            con.execute("INSERT INTO contas (id, empresa_id, descricao, tipo, saldo_inicial) VALUES (?, 1, ?, ?, ?)",
                        (i, name, "C" if is_cash else "B", float(start)))
            acc_id[name] = i

        # centros: os usados nos lançamentos; vale para despesa/receita conforme o uso
        used: dict[str, set] = {}
        for r in entries:
            if r.get("CENTRO DE CUSTO"):
                used.setdefault(r["CENTRO DE CUSTO"], set()).add("R" if _key(r["TIPO"]).startswith("REC") else "D")
        cc_id = {}
        for i, (name, kinds) in enumerate(sorted(used.items()), start=1):
            con.execute("INSERT INTO centros (id, empresa_id, nome, aplica_despesa, aplica_receita) VALUES (?, 1, ?, ?, ?)",
                        (i, name, int("D" in kinds), int("R" in kinds)))
            cc_id[name] = i

        for i, p in enumerate(_people(b), start=1):
            con.execute("""INSERT INTO pessoas (id, empresa_id, tipo, pessoa, nome, documento, endereco, bairro, cidade,
                           uf, cep, telefone, email) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (i, p["_tipo"], _person(p.get("DOCUMENTO")), p["NOME"].strip(),
                         re.sub(r"\D", "", p.get("DOCUMENTO") or "") or None, p.get("ENDERECO") or None,
                         p.get("BAIRRO") or None, p.get("CIDADE") or None, p.get("ESTADO") or None,
                         p.get("CEP") or None, p.get("TELEFONE") or None, p.get("E-MAIL") or None))

        # data de pagamento: a do extrato da conta (PAGTO.:/REC.: descrição, mesmo valor)
        paid_at: dict[tuple, list[date]] = {}
        moves: list[tuple] = []                            # (conta, data, crédito, débito, texto, obs)
        for s in b.of("extrato"):
            acc = next((n for n in acc_id if _key(n) == _key(s.account)), None) or \
                (next((n for n in acc_id if n in cash or "CAIXA" in _key(n)), None) if s.cash else None)
            if acc is None:
                b.warnings.append(f"{s.path.name}: não achei a conta \"{s.account}\" nos lançamentos; extrato ignorado.")
                continue
            for r in s.rows:
                m = re.match(r"(PAGTO|REC)\.:\s*(.*)", r.get("MOV", ""))
                value = _money(r.get("DEBITO")) or _money(r.get("CREDITO"))
                if m:
                    k = (acc, "D" if m.group(1) == "PAGTO" else "R", _key(m.group(2)), value)
                    paid_at.setdefault(k, []).append(parse_date(r["DATA"]))
                else:
                    moves.append((acc, parse_date(r["DATA"]), _money(r.get("CREDITO")), _money(r.get("DEBITO")),
                                  r.get("MOV", ""), r.get("OBS", "")))
        items = set()
        for i, r in enumerate(entries, start=1):
            tipo = "R" if _key(r["TIPO"]).startswith("REC") else "D"
            value = _money(r["VALOR"])
            paid = _key(r["MOVSIT"]) == "V"
            due = parse_date(r["VENCIMENTO"]) or parse_date(r["DATA"])
            pay = None
            if paid:
                options = paid_at.get((r.get("CONTA"), tipo, _key(r["DESCRICAO"]), value)) or []
                if options:
                    pay = min(options, key=lambda d: abs((d - due).days))
                    options.remove(pay)
                    b.paid_dates_found += 1
                else:
                    b.paid_dates_missing += 1
            items.add((tipo, r["DESCRICAO"].strip()))
            con.execute("""INSERT INTO lancamentos (id, empresa_id, tipo, data_mov, documento, descricao, pessoa, valor,
                           situacao, vencimento, data_pagamento, observacao, conta_id, centro_id, criado_em)
                           VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (i, tipo, _iso(r["DATA"]), r.get("DOCUMENTO") or None, r["DESCRICAO"].strip(),
                         r.get("NOME") or None, float(value), "V" if paid else "P", due.isoformat(),
                         pay.isoformat() if pay else None, r.get("OBSERVACAO") or None, acc_id.get(r.get("CONTA")),
                         cc_id.get(r.get("CENTRO DE CUSTO")), f"{_iso(r['DATA'])} 00:00:00"))
        for i, (tipo, desc) in enumerate(sorted(items), start=1):
            con.execute("INSERT INTO itens (id, empresa_id, tipo, descricao) VALUES (?, 1, ?, ?)", (i, tipo, desc))
        if b.paid_dates_missing:
            b.warnings.append(f"{b.paid_dates_missing} pago(s) sem a linha no extrato da conta: entram com o "
                              "vencimento como data de pagamento (falta o extrato dessa conta?).")

        # transferências: saída numa conta + entrada noutra, mesma data e valor
        outs = [m for m in moves if m[3]]
        ins = [m for m in moves if m[2]]
        n = 0
        for o in outs:
            pair = next((x for x in ins if x[1] == o[1] and x[2] == o[3] and x[0] != o[0]), None)
            if pair is None:
                b.left_out.append(f"{o[1]:%d/%m/%Y} {o[4]} ({o[0]}) R$ {o[3]}")
                continue
            ins.remove(pair)
            n += 1
            con.execute("""INSERT INTO movbancarias (id, empresa_id, tipo, situacao, data, origem_id, destino_id, valor,
                           observacao) VALUES (?, 1, 'T', 'V', ?, ?, ?, ?, ?)""",
                        (n, o[1].isoformat(), acc_id[o[0]], acc_id[pair[0]], float(o[3]), o[5] or pair[5] or None))
        for x in ins:
            b.left_out.append(f"{x[1]:%d/%m/%Y} {x[4]} ({x[0]}) R$ {x[2]}")
        b.transfers = n
        if b.left_out:
            b.warnings.append(f"{len(b.left_out)} movimentação(ões) de um lado só nos extratos ficaram de fora "
                              "(sem a outra conta, como no saldo do próprio MCC).")
        con.commit()

        # conferência com o rodapé dos extratos (o saldo que o MCC mostra)
        for s in b.of("extrato"):
            acc = next((nm for nm in acc_id if _key(nm) == _key(s.account)), None) or \
                (next((nm for nm in acc_id if nm in cash or "CAIXA" in _key(nm)), None) if s.cash else None)
            if acc is None or s.final is None:
                continue
            aid = acc_id[acc]
            row = con.execute("""SELECT
                  (SELECT saldo_inicial FROM contas WHERE id=?)
                + COALESCE((SELECT SUM(CASE tipo WHEN 'R' THEN valor ELSE -valor END) FROM lancamentos
                            WHERE conta_id=? AND situacao='V'), 0)
                + COALESCE((SELECT SUM(valor) FROM movbancarias WHERE destino_id=?), 0)
                - COALESCE((SELECT SUM(valor) FROM movbancarias WHERE origem_id=?), 0)""",
                              (aid, aid, aid, aid)).fetchone()
            b.balances.append(BalanceCheck(acc, s.final, Decimal(str(round(row[0], 2))).quantize(ZERO)))
        for c in b.balances:
            if not c.ok:
                b.warnings.append(f"{c.account}: o saldo final do MCC é {c.expected} e o montado pelas planilhas dá "
                                  f"{c.rebuilt} (falta algum relatório ou extrato?).")
    finally:
        con.close()
    return dest
