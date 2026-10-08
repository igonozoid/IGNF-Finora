"""Importar extrato OFX e conciliar: casar cada linha do banco com um lançamento do Finora.

Fluxo: importar_ofx() guarda as linhas (sem repetir as já importadas) -> lines() mostra cada linha com uma
sugestão: um lançamento já existente (mesmo valor, data próxima) ou um lançamento novo (com a categoria que
você usou da última vez para algo parecido) -> confirm()/create()/ignore().
"""
import hashlib
import io
import re
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from finora.models import Account, BankLine, Category, Contact, Entry
from finora.services import entries
from finora.services.entries import EntryData

DAYS = 5   # tolerância de datas entre o extrato e o lançamento (compensação, fim de semana…)


@dataclass(frozen=True)
class OfxLine:
    fitid: str
    posted: date
    amount: Decimal      # + entrou, − saiu
    memo: str


@dataclass(frozen=True)
class ImportResult:
    new: int
    repeated: int
    auto_matched: int
    first: date | None
    last: date | None


@dataclass(frozen=True)
class Suggestion:
    kind: str                    # "entry" (já existe) | "new" (criar)
    entry_id: int | None
    description: str
    category_id: int | None
    category: str | None
    contact: str | None
    when: date | None = None     # vencimento/pagamento do lançamento sugerido


@dataclass(frozen=True)
class LineView:
    id: int
    posted: date
    amount: Decimal
    memo: str
    status: str                  # pending | matched | ignored
    entry_id: int | None
    linked: str | None           # descrição do lançamento ligado
    suggestion: Suggestion | None


# ---------- leitura do OFX ----------
def parse_ofx(data: bytes) -> list[OfxLine]:
    """Lê o arquivo OFX do banco. Levanta ValueError com mensagem pronta se não for um extrato."""
    import ofxparse
    try:
        with warnings.catch_warnings():       # o ofxparse usa APIs antigas do BeautifulSoup (só avisos)
            warnings.simplefilter("ignore", DeprecationWarning)
            ofx = ofxparse.OfxParser.parse(io.BytesIO(data))
        accounts = ofx.accounts or ([ofx.account] if getattr(ofx, "account", None) else [])
        txs = [t for a in accounts for t in a.statement.transactions]
    except Exception as exc:     # o ofxparse levanta vários tipos; para o usuário é tudo "arquivo inválido"
        raise ValueError("Não consegui ler esse arquivo. Confira se é um extrato no formato OFX "
                         "(no site ou app do banco: Extrato › Exportar › OFX/Money).") from exc
    out = []
    for t in txs:
        amount = Decimal(str(t.amount)).quantize(Decimal("0.01"))
        when = t.date.date() if isinstance(t.date, datetime) else t.date
        memo = " ".join(str(t.memo or t.payee or "").split())[:200]
        fitid = str(t.id or "").strip()
        if not fitid:            # alguns bancos não mandam o id: monta um a partir do conteúdo
            fitid = "h" + hashlib.sha1(f"{when}|{amount}|{memo}".encode()).hexdigest()[:20]
        out.append(OfxLine(fitid[:80], when, amount, memo))
    if not out:
        raise ValueError("O arquivo não tem nenhuma movimentação no período.")
    return out


def import_ofx(s: Session, entity_id: int, account_id: int, data: bytes) -> ImportResult:
    return import_lines(s, entity_id, account_id, parse_ofx(data))


def import_lines(s: Session, entity_id: int, account_id: int, lines: list[OfxLine]) -> ImportResult:
    """Grava as linhas do extrato (OFX ou planilha) que ainda não estão lá e liga sozinho o que não deixa dúvida."""
    acc = s.get(Account, account_id)
    if acc is None or acc.entity_id != entity_id:
        raise ValueError("Escolha a conta do extrato.")
    known = set(s.scalars(select(BankLine.fitid).where(BankLine.account_id == account_id)))
    new = []
    for ln in lines:
        if ln.fitid in known:
            continue
        known.add(ln.fitid)
        new.append(BankLine(entity_id=entity_id, account_id=account_id, fitid=ln.fitid, posted=ln.posted,
                            amount=ln.amount, memo=ln.memo, status="pending"))
    s.add_all(new)
    s.flush()
    auto = _auto_match(s, new)
    s.commit()
    dates = [ln.posted for ln in lines]
    return ImportResult(len(new), len(lines) - len(new), auto, min(dates), max(dates))


# ---------- sugestões ----------
def _norm(text: str) -> str:
    """'PIX ENV J PEREIRA 12/09' -> 'pix env j pereira' (sem números, datas e espaços extras)."""
    return " ".join(re.sub(r"[\d/.,:*-]+", " ", (text or "").lower()).split())


def _linked_entry_ids(s: Session, account_id: int) -> set[int]:
    return set(s.scalars(select(BankLine.entry_id).where(BankLine.account_id == account_id,
                                                         BankLine.entry_id.is_not(None))))


def _candidates(s: Session, line: BankLine, taken: set[int]) -> list[Entry]:
    """Lançamentos da conta com o mesmo valor e data perto da linha do extrato, mais perto primeiro."""
    amount = abs(line.amount)
    first, last = line.posted - timedelta(days=DAYS), line.posted + timedelta(days=DAYS)
    if line.amount > 0:      # entrou: receita na conta ou transferência chegando nela
        side = or_((Entry.kind == "income") & (Entry.account_id == line.account_id) & (Entry.amount == amount),
                   (Entry.kind == "transfer") & (Entry.dest_account_id == line.account_id)
                   & (func.coalesce(Entry.dest_amount, Entry.amount) == amount))
    else:                    # saiu: despesa ou transferência saindo dela
        side = (Entry.kind.in_(("expense", "transfer"))) & (Entry.account_id == line.account_id)             & (Entry.amount == amount)
    rows = s.scalars(select(Entry).where(
        Entry.entity_id == line.entity_id, side, Entry.status.in_(("pending", "paid")),
        or_((Entry.status == "pending") & Entry.due_date.between(first, last),
            (Entry.status == "paid") & Entry.paid_date.between(first, last))))
    found = [e for e in rows if e.id not in taken]
    return sorted(found, key=lambda e: (abs(((e.paid_date or e.due_date) - line.posted).days), e.id))


def _auto_match(s: Session, new: list[BankLine]) -> int:
    """Liga sozinho o que não deixa dúvida: um único lançamento JÁ PAGO, mesmo valor, data próxima."""
    if not new:
        return 0
    taken = _linked_entry_ids(s, new[0].account_id)
    n = 0
    for line in new:
        cands = [e for e in _candidates(s, line, taken) if e.status == "paid"]
        if len(cands) == 1:
            line.status, line.entry_id = "matched", cands[0].id
            taken.add(cands[0].id)
            n += 1
    return n


def _learned(s: Session, line: BankLine) -> Suggestion:
    """Lançamento novo: as regras automáticas (Categorias › Regras) mandam; sem regra, copia categoria/contato do
    último parecido que você já conciliou."""
    from finora.services import rules
    kind = "income" if line.amount > 0 else "expense"
    sug = _from_history(s, line, kind)
    rule = rules.match(s, line.entity_id, line.memo, kind)
    if rule is None:
        return sug
    return Suggestion("new", None, rule.description or sug.description, rule.category_id or sug.category_id,
                      rule.category if rule.category_id else sug.category, rule.contact or sug.contact)


def _from_history(s: Session, line: BankLine, kind: str) -> Suggestion:
    key = _norm(line.memo)
    if key:
        prev = s.execute(
            select(Entry, Category.name, Contact.name, BankLine.memo)
            .join(BankLine, BankLine.entry_id == Entry.id)
            .outerjoin(Category, Category.id == Entry.category_id)
            .outerjoin(Contact, Contact.id == Entry.contact_id)
            .where(BankLine.entity_id == line.entity_id, BankLine.id != line.id, Entry.kind == kind)
            .order_by(BankLine.posted.desc())).all()
        for e, cat, contact, memo in prev:
            if _norm(memo) == key:
                return Suggestion("new", None, e.description or line.memo, e.category_id, cat, contact)
    return Suggestion("new", None, _pretty(line.memo), None, None, None)


def _pretty(memo: str) -> str:
    """'PAG BOLETO ENEL' -> 'Pag boleto enel' (descrição inicial legível)."""
    memo = " ".join(memo.split())
    return memo[:1].upper() + memo[1:].lower() if memo else "Movimentação do extrato"


def lines(s: Session, entity_id: int, account_id: int, show: str = "pending") -> list[LineView]:
    """show: 'pending' (falta conciliar) | 'all'. Mais recentes primeiro."""
    # lançamento excluído depois de conciliado: a linha volta a ficar pendente
    for orphan in s.scalars(select(BankLine).where(BankLine.account_id == account_id,
                                                   BankLine.status == "matched", BankLine.entry_id.is_(None))):
        orphan.status = "pending"
    s.flush()
    q = select(BankLine).where(BankLine.entity_id == entity_id, BankLine.account_id == account_id)
    if show == "pending":
        q = q.where(BankLine.status == "pending")
    taken = _linked_entry_ids(s, account_id)
    out = []
    for line in s.scalars(q.order_by(BankLine.posted.desc(), BankLine.id.desc())):
        linked = sug = None
        if line.entry_id:
            e = s.get(Entry, line.entry_id)
            linked = e.description if e else None
        elif line.status == "pending":
            cands = _candidates(s, line, taken)
            if cands:
                e = cands[0]
                cat = s.get(Category, e.category_id) if e.category_id else None
                contact = s.get(Contact, e.contact_id) if e.contact_id else None
                sug = Suggestion("entry", e.id, e.description or "", e.category_id, cat.name if cat else None,
                                 contact.name if contact else None, e.paid_date or e.due_date)
                taken.add(e.id)      # a mesma conta não é sugerida para duas linhas
            else:
                sug = _learned(s, line)
        out.append(LineView(line.id, line.posted, line.amount, line.memo, line.status, line.entry_id, linked, sug))
    s.commit()
    return out


def counts(s: Session, entity_id: int, account_id: int) -> dict[str, int]:
    rows = s.scalars(select(BankLine.status).where(BankLine.entity_id == entity_id,
                                                   BankLine.account_id == account_id)).all()
    return {k: rows.count(k) for k in ("pending", "matched", "ignored")}


# ---------- ações ----------
def _line(s: Session, line_id: int) -> BankLine:
    line = s.get(BankLine, line_id)
    if line is None:
        raise ValueError("Linha do extrato não encontrada.")
    return line


def confirm(s: Session, line_id: int, entry_id: int) -> None:
    """Liga a linha ao lançamento. Se ele estava em aberto, fica pago na data do extrato."""
    line = _line(s, line_id)
    e = s.get(Entry, entry_id)
    if e is None or e.entity_id != line.entity_id:
        raise ValueError("Lançamento não encontrado.")
    if entry_id in _linked_entry_ids(s, line.account_id):
        raise ValueError("Esse lançamento já está ligado a outra linha do extrato.")
    arrived = e.dest_amount if e.kind == "transfer" and e.dest_account_id == line.account_id and e.dest_amount         else e.amount
    if abs(line.amount) != arrived:
        raise ValueError("O valor do lançamento é diferente do valor do extrato.")
    if e.status == "pending":
        e.status, e.paid_date = "paid", line.posted
    line.status, line.entry_id = "matched", e.id
    s.commit()


def create(s: Session, line_id: int, description: str, category_id: int | None,
           contact: str | None = None) -> int:
    """Cria um lançamento já pago a partir da linha do extrato e liga os dois."""
    line = _line(s, line_id)
    kind = "income" if line.amount > 0 else "expense"
    (entry_id,) = entries.create(s, line.entity_id, EntryData(
        kind=kind, description=(description or "").strip() or _pretty(line.memo), amount=abs(line.amount),
        due_date=line.posted, account_id=line.account_id, category_id=category_id, contact=contact,
        paid=True, paid_date=line.posted))
    line.status, line.entry_id = "matched", entry_id
    s.commit()
    return entry_id


def ignore(s: Session, line_id: int) -> None:
    """Linha que não vira lançamento (ex.: aplicação automática já controlada em outro lugar)."""
    line = _line(s, line_id)
    line.status, line.entry_id = "ignored", None
    s.commit()


def undo(s: Session, line_id: int) -> None:
    """Volta a linha para "falta conciliar". O lançamento ligado continua existindo."""
    line = _line(s, line_id)
    line.status, line.entry_id = "pending", None
    s.commit()

