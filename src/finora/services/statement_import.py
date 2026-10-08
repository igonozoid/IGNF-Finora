"""Extrato ou fatura em planilha (CSV ou Excel) para a conciliação, para bancos e cartões que não dão OFX.

Cada banco monta a planilha de um jeito: o Finora adivinha as colunas (data, descrição, valor ou entrada/saída)
e a pessoa confere numa prévia antes de importar. As linhas viram linhas de extrato (BankLine), igual ao OFX, com
um identificador tirado do conteúdo: importar o mesmo arquivo de novo não duplica nada.
"""
import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from finora.core.money import CENT
from finora.services.reconcile import OfxLine

MAX_ROWS = 20000
_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y %H:%M",
                 "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")


@dataclass
class Mapping:
    header_row: int = 0                 # linha com os títulos (-1 = não tem); dados começam depois
    date_col: int = -1
    desc_col: int = -1
    amount_col: int = -1                # valor com sinal (ou D/C)…
    in_col: int = -1                    # …ou duas colunas: entrada e saída
    out_col: int = -1
    invert: bool = False                # fatura de cartão: compras vêm positivas -> viram saídas

    @property
    def ready(self) -> bool:
        return self.date_col >= 0 and self.desc_col >= 0 and (self.amount_col >= 0 or self.in_col >= 0
                                                               or self.out_col >= 0)


# ---------- leitura ----------
def read_table(data: bytes, filename: str) -> list[list[str]]:
    """Linhas da planilha como texto. Excel (.xlsx) pela 1ª aba; CSV com ; , ou tab, em UTF-8 ou Windows."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(data)
    if name.endswith(".xls"):
        raise ValueError("Planilha .xls (Excel antigo) não é aceita. Abra no Excel e salve como .xlsx ou CSV.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Não consegui ler o texto do arquivo.")
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") >= sample.count(",") else ","
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
    rows = [r for r in rows if any(r)]
    if not rows:
        raise ValueError("O arquivo está vazio.")
    return rows[:MAX_ROWS]


def _read_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("Não consegui abrir a planilha do Excel.") from exc
    ws = wb.worksheets[0]
    rows = []
    for r in ws.iter_rows(values_only=True):
        cells = []
        for v in r:
            if v is None:
                cells.append("")
            elif isinstance(v, datetime):
                cells.append(v.strftime("%d/%m/%Y"))
            elif isinstance(v, date):
                cells.append(v.strftime("%d/%m/%Y"))
            elif isinstance(v, float):
                cells.append(f"{Decimal(str(v)).quantize(CENT)}")
            else:
                cells.append(str(v).strip())
        if any(cells):
            rows.append(cells)
        if len(rows) >= MAX_ROWS:
            break
    wb.close()
    if not rows:
        raise ValueError("A planilha está vazia.")
    return rows


# ---------- valores ----------
def parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if re.fullmatch(r"\d{5}(\.0)?", text):            # número de série do Excel
        return date(1899, 12, 30) + timedelta(days=int(float(text)))
    return None


def parse_amount(text: str) -> Decimal | None:
    """'1.234,56' · '-1.234,56' · '1,234.56' · '(50,00)' · '50,00 D' · 'R$ -10,00' · '−3,5'."""
    s = (text or "").strip().replace("−", "-").replace("R$", "").replace("US$", "").replace("$", "")
    s = s.replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    sign = 1
    if s.startswith("(") and s.endswith(")"):
        sign, s = -1, s[1:-1]
    if s[-1:].upper() in ("D", "C") and re.search(r"\d", s[:-1]):
        sign, s = (-1 if s[-1].upper() == "D" else 1) * sign, s[:-1]
    if s.endswith("-"):
        sign, s = -sign, s[:-1]
    if s.startswith("-"):
        sign, s = -sign, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    try:
        return (sign * Decimal(s)).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _key(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


# ---------- adivinhar as colunas ----------
_DATE_WORDS = ("data", "date", "dt", "lancamento", "movimento")
_DESC_WORDS = ("descricao", "historico", "lancamento", "description", "memo", "detalhe", "estabelecimento", "titulo")
_AMOUNT_WORDS = ("valor", "amount", "value", "quantia", "montante")
_IN_WORDS = ("entrada", "credito", "receita", "deposito")
_OUT_WORDS = ("saida", "debito", "despesa", "pagamento", "saque")


def guess(rows: list[list[str]]) -> Mapping:
    m = Mapping()
    width = max(len(r) for r in rows)
    # títulos: a primeira linha (entre as 10 primeiras) sem nenhuma data e com algum texto
    m.header_row = -1
    for i, r in enumerate(rows[:10]):
        if any(parse_date(c) for c in r):
            break
        if sum(1 for c in r if c and parse_amount(c) is None) >= 2:
            m.header_row = i
    titles = [_key(c) for c in rows[m.header_row]] if m.header_row >= 0 else [""] * width
    data = rows[m.header_row + 1:m.header_row + 41]

    def share(col: int, fn) -> float:
        vals = [r[col] for r in data if col < len(r) and r[col]]
        return sum(1 for v in vals if fn(v) is not None) / len(vals) if vals else 0

    def by_title(words) -> int:
        for w in words:
            for c, t in enumerate(titles):
                if w in t:
                    return c
        return -1

    m.date_col = by_title(_DATE_WORDS)
    if m.date_col < 0 or share(m.date_col, parse_date) < 0.6:
        m.date_col = next((c for c in range(width) if share(c, parse_date) >= 0.8), -1)
    m.in_col, m.out_col = by_title(_IN_WORDS), by_title(_OUT_WORDS)
    m.amount_col = by_title(_AMOUNT_WORDS)
    if m.amount_col in (m.in_col, m.out_col):
        m.amount_col = -1
    if m.amount_col >= 0 or not (m.in_col >= 0 and m.out_col >= 0):
        m.in_col = m.out_col = -1
        if m.amount_col < 0 or share(m.amount_col, parse_amount) < 0.6:
            nums = [c for c in range(width) if c != m.date_col and share(c, parse_amount) >= 0.8]
            m.amount_col = nums[0] if nums else -1     # saldo costuma vir depois do valor
    used = {m.date_col, m.amount_col, m.in_col, m.out_col}
    m.desc_col = by_title(_DESC_WORDS)
    if m.desc_col < 0 or m.desc_col in used:
        texts = [c for c in range(width) if c not in used and share(c, lambda v: v if parse_amount(v) is None
                                                                      and parse_date(v) is None else None) > 0.5]
        m.desc_col = max(texts, key=lambda c: sum(len(r[c]) for r in data if c < len(r)), default=-1)
    return m


# ---------- converter ----------
@dataclass(frozen=True)
class Parsed:
    lines: list[OfxLine]
    skipped: int                 # linhas sem data/valor (saldo, títulos, totais)


def parse(rows: list[list[str]], m: Mapping) -> Parsed:
    if not m.ready:
        raise ValueError("Escolha as colunas de data, descrição e valor.")
    out, skipped, seen = [], 0, {}
    for r in rows[m.header_row + 1:]:
        def cell(c: int) -> str:
            return r[c] if 0 <= c < len(r) else ""
        when = parse_date(cell(m.date_col))
        if m.amount_col >= 0:
            amount = parse_amount(cell(m.amount_col))
        else:
            inc, out_ = parse_amount(cell(m.in_col)), parse_amount(cell(m.out_col))
            amount = None if inc is None and out_ is None else (abs(inc or 0) - abs(out_ or 0))
        memo = " ".join(cell(m.desc_col).split())[:200]
        if when is None or amount is None or amount == 0 or _key(memo).startswith(("saldo", "total")):
            skipped += 1
            continue
        if m.invert:
            amount = -amount
        base = f"{when}|{amount}|{_key(memo)}"
        n = seen[base] = seen.get(base, 0) + 1         # duas compras iguais no mesmo dia são duas linhas
        fitid = "p" + hashlib.sha1(f"{base}|{n}".encode()).hexdigest()[:24]
        out.append(OfxLine(fitid, when, Decimal(amount).quantize(CENT), memo or "Movimentação"))
    if not out:
        raise ValueError("Nenhuma linha com data e valor nas colunas escolhidas.")
    return Parsed(out, skipped)
