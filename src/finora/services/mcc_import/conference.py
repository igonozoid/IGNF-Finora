"""Relatório de conferência da importação do MCC (Fase 2.7).

Para cada conta importada, em algumas datas, compara o saldo realizado e o previsto do MCC (pela regra do próprio
MCC: `finance.saldos` do clone) com os do Finora. Diferenças explicadas não contam como erro:

- lançamento pago sem data de pagamento (decisão D6): no MCC ficava fora do saldo; no Finora entra no vencimento;
- arredondamento de valor com mais de 2 casas (Fase 2.4).

Também confere, por empresa, a quantidade de lançamentos e os totais a pagar, a receber, pago e recebido. Se sobrar
diferença sem explicação, `ok` é False e a tela da importação não deixa concluir.
"""
import calendar
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from finora.models import Account, Entry
from finora.services import export
from finora.services.mcc_import.mapper import ImportResult

TOLERANCE = Decimal("0.01")
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class BalanceCheck:
    account: str
    mcc_account: int
    day: date
    mcc_real: Decimal
    finora_real: Decimal
    mcc_forecast: Decimal
    finora_forecast: Decimal
    explained_real: Decimal        # parte explicada da diferença (D6 + arredondamento) no realizado
    explained_forecast: Decimal    # … e no previsto (arredondamento de lançamento em aberto só mexe nele)

    @property
    def unexplained(self) -> Decimal:
        """Maior diferença sem explicação entre realizado e previsto."""
        return max(abs(self.finora_real - self.mcc_real - self.explained_real),
                   abs(self.finora_forecast - self.mcc_forecast - self.explained_forecast))

    @property
    def ok(self) -> bool:
        return self.unexplained < TOLERANCE


@dataclass(frozen=True)
class TotalCheck:
    company: str
    label: str
    mcc: Decimal
    finora: Decimal
    explained: Decimal = ZERO

    @property
    def ok(self) -> bool:
        return abs(self.finora - self.mcc - self.explained) < TOLERANCE


@dataclass
class Conference:
    days: list[date]
    balances: list[BalanceCheck] = field(default_factory=list)
    totals: list[TotalCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(b.ok for b in self.balances) and all(t.ok for t in self.totals)

    @property
    def problems(self) -> list[str]:
        out = [f"{b.account} em {b.day:%d/%m/%Y}: diferença de {b.unexplained} sem explicação"
               for b in self.balances if not b.ok]
        out += [f"{t.company} — {t.label}: MCC {t.mcc} × Finora {t.finora}" for t in self.totals if not t.ok]
        return out


def _r2(v) -> Decimal:
    return Decimal(repr(float(v or 0))).quantize(Decimal("0.01"))


def default_days(con: sqlite3.Connection, today: date | None = None) -> list[date]:
    """Fim do mês passado, hoje e a última data do MCC (vencimentos e movimentações futuras)."""
    today = today or date.today()
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    last_month = date(y, m, calendar.monthrange(y, m)[1])
    latest = con.execute("SELECT MAX(d) FROM (SELECT MAX(vencimento) d FROM lancamentos UNION ALL "
                         "SELECT MAX(data_pagamento) FROM lancamentos UNION ALL SELECT MAX(data) FROM movbancarias)"
                         ).fetchone()[0]
    days = {last_month, today}
    if latest:
        days.add(max(date.fromisoformat(latest[:10]), today))
    return sorted(days)


def mcc_balance(con: sqlite3.Connection, account_id: int, day: date) -> tuple[Decimal, Decimal]:
    """(realizado, previsto) de uma conta do MCC numa data, pela regra do MCC (finance.saldos do clone)."""
    ate = day.isoformat()
    opening = con.execute("SELECT saldo_inicial FROM contas WHERE id=?", (account_id,)).fetchone()[0]
    real, prev = con.execute("""SELECT
        COALESCE(SUM(CASE WHEN situacao='V' AND data_pagamento<=? THEN (CASE tipo WHEN 'R' THEN valor ELSE -valor END) END),0),
        COALESCE(SUM(CASE WHEN (situacao='V' AND data_pagamento<=?) OR (situacao='P' AND vencimento<=?)
            THEN (CASE tipo WHEN 'R' THEN valor ELSE -valor END) END),0)
        FROM lancamentos WHERE conta_id=? AND excluido_em IS NULL""", (ate, ate, ate, account_id)).fetchone()
    m_real, m_prev = con.execute("""SELECT COALESCE(SUM(CASE WHEN situacao='V' THEN v END),0), COALESCE(SUM(v),0) FROM (
          SELECT situacao, CASE tipo WHEN 'D' THEN valor ELSE -valor END AS v FROM movbancarias
            WHERE origem_id=? AND data<=? AND excluido_em IS NULL
          UNION ALL
          SELECT situacao, valor FROM movbancarias WHERE tipo='T' AND destino_id=? AND data<=? AND excluido_em IS NULL)""",
                                 (account_id, ate, account_id, ate)).fetchone()
    return _r2(opening + real + m_real), _r2(opening + prev + m_prev)


def finora_balance(s: Session, account_id: int, day: date) -> tuple[Decimal, Decimal]:
    """(realizado, previsto) de uma conta do Finora numa data: pagos até a data; previsto soma os em aberto que vencem
    até ela. Vale para lançamentos de qualquer entidade (conta compartilhada)."""
    acc = s.get(Account, account_id)
    real = prev = Decimal(acc.opening_balance)
    q = select(Entry).where(or_(Entry.account_id == account_id, Entry.dest_account_id == account_id))
    for e in s.scalars(q):
        if e.kind == "transfer" and e.dest_account_id == account_id:
            v = Decimal(e.dest_amount if e.dest_amount is not None else e.amount)
        else:
            v = Decimal(e.amount) if e.kind in ("income", "deposit") else -Decimal(e.amount)
        if e.status == "paid" and e.paid_date and e.paid_date <= day:
            real += v
            prev += v
        elif e.status == "pending" and e.due_date <= day:
            prev += v
    return real.quantize(TOLERANCE), prev.quantize(TOLERANCE)


def _explained(con: sqlite3.Connection, r: ImportResult, mcc_account: int, day: date) -> tuple[Decimal, Decimal]:
    """Quanto da diferença da conta numa data é explicado (realizado, previsto): D6 e arredondamentos."""
    real = forecast = ZERO
    ate = day.isoformat()
    for lid in r.paid_without_date:                    # D6: entra pago no vencimento; no MCC não contava
        row = con.execute("SELECT tipo, valor, vencimento, conta_id FROM lancamentos WHERE id=?", (lid,)).fetchone()
        if row["conta_id"] == mcc_account and row["vencimento"] <= ate:
            v = _r2(row["valor"]) if row["tipo"] == "R" else -_r2(row["valor"])
            real, forecast = real + v, forecast + v
    for rd in r.rounding:
        if rd.table == "contas" and rd.mcc_id == mcc_account and rd.column == "saldo_inicial":
            real, forecast = real + rd.difference, forecast + rd.difference
        elif rd.table in ("lancamentos", "movbancarias") and rd.column == "valor":
            dr, df = _rounding_effect(con, rd, mcc_account, ate)
            real, forecast = real + dr, forecast + df
    return real, forecast


def _rounding_effect(con: sqlite3.Connection, rd, mcc_account: int, ate: str) -> tuple[Decimal, Decimal]:
    """Efeito do arredondamento de um valor no saldo (realizado, previsto) da conta até a data."""
    if rd.table == "lancamentos":
        row = con.execute("SELECT tipo, situacao, vencimento, data_pagamento, conta_id FROM lancamentos WHERE id=?",
                          (rd.mcc_id,)).fetchone()
        if row["conta_id"] != mcc_account:
            return ZERO, ZERO
        v = rd.difference if row["tipo"] == "R" else -rd.difference
        if row["situacao"] == "V":
            return (v, v) if (row["data_pagamento"] or row["vencimento"]) <= ate else (ZERO, ZERO)
        return ZERO, (v if row["vencimento"] <= ate else ZERO)
    row = con.execute("SELECT tipo, situacao, data, origem_id, destino_id FROM movbancarias WHERE id=?",
                      (rd.mcc_id,)).fetchone()
    if row["data"] > ate:
        return ZERO, ZERO
    if row["origem_id"] == mcc_account:
        v = rd.difference if row["tipo"] == "D" else -rd.difference
    elif row["tipo"] == "T" and row["destino_id"] == mcc_account:
        v = rd.difference
    else:
        return ZERO, ZERO
    return (v, v) if row["situacao"] == "V" else (ZERO, v)


def build(s: Session, con: sqlite3.Connection, r: ImportResult, days: list[date] | None = None) -> Conference:
    """Monta a conferência. `con` é a mesma cópia do MCC usada na importação (reader.open_copy)."""
    days = days or default_days(con)
    rep = Conference(days)
    names = {row["id"]: row["descricao"] for row in con.execute("SELECT id, descricao FROM contas")}
    for mcc_acc, acc_id in sorted(r.accounts.items()):
        for day in days:
            m_real, m_prev = mcc_balance(con, mcc_acc, day)
            f_real, f_prev = finora_balance(s, acc_id, day)
            rep.balances.append(BalanceCheck(names[mcc_acc], mcc_acc, day, m_real, f_real, m_prev, f_prev,
                                             *_explained(con, r, mcc_acc, day)))
    by_mcc = {v: k for k, v in r.entries.items()}
    for mcc_id, eid in r.entities.items():
        company = con.execute("SELECT nome FROM empresas WHERE id=?", (mcc_id,)).fetchone()[0]
        mcc_rows = con.execute("SELECT id, tipo, situacao, valor FROM lancamentos WHERE empresa_id=? "
                               "AND excluido_em IS NULL", (mcc_id,)).fetchall()
        fin = [e for e in s.scalars(select(Entry).where(Entry.entity_id == eid, Entry.kind.in_(("income", "expense"))))
               if e.id in by_mcc]
        rep.totals.append(TotalCheck(company, "Lançamentos", Decimal(len(mcc_rows)), Decimal(len(fin))))
        rounding = {rd.mcc_id: rd.difference for rd in r.rounding if rd.table == "lancamentos"}
        for label, tipo, sit, kind, status in (("A pagar", "D", "P", "expense", "pending"),
                                               ("A receber", "R", "P", "income", "pending"),
                                               ("Pago", "D", "V", "expense", "paid"),
                                               ("Recebido", "R", "V", "income", "paid")):
            sel = [x for x in mcc_rows if x["tipo"] == tipo and x["situacao"] == sit]
            rep.totals.append(TotalCheck(
                company, label, sum((_r2(x["valor"]) for x in sel), ZERO),
                sum((Decimal(e.amount) for e in fin if e.kind == kind and e.status == status), ZERO),
                sum((rounding.get(x["id"], ZERO) for x in sel), ZERO)))
    if r.paid_without_date:
        rep.notes.append(f"{len(r.paid_without_date)} lançamento(s) pago(s) sem data de pagamento no MCC entraram com "
                         "a data do vencimento (no MCC eles não contavam no saldo): diferença explicada.")
    if r.rounding:
        rep.notes.append(f"{len(r.rounding)} valor(es) com mais de 2 casas no MCC foram arredondados: diferença "
                         "explicada.")
    if r.contacts_created_from_text:
        rep.notes.append(f"{len(r.contacts_created_from_text)} contato(s) criado(s) a partir do nome solto, marcados "
                         "\"A revisar\": " + ", ".join(r.contacts_created_from_text) + ".")
    rep.notes += r.warnings
    return rep


def to_sheet(rep: Conference, currency: str = "BRL") -> export.Sheet:
    """Planilha da conferência (Excel/PDF pela exportação de sempre)."""
    sheet = export.Sheet("Conferência da importação do MCC",
                         "Bateu" if rep.ok else f"{len(rep.problems)} diferença(s) sem explicação",
                         ["Conta / empresa", "Data / total", "MCC realizado", "Finora realizado", "MCC previsto",
                          "Finora previsto", "Explicado", "Situação"], currency=currency)
    for b in rep.balances:
        sheet.add([b.account, b.day, b.mcc_real, b.finora_real, b.mcc_forecast, b.finora_forecast, b.explained_real,
                   "ok" if b.ok else "NÃO BATEU"], "" if b.ok else "bold")
    for t in rep.totals:
        sheet.add([t.company, t.label, t.mcc, t.finora, None, None, t.explained, "ok" if t.ok else "NÃO BATEU"],
                  "" if t.ok else "bold")
    sheet.footer = " · ".join(rep.notes)
    return sheet
