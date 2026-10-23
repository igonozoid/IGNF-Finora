"""Movimentação de dinheiro lançada como receita/despesa (decisão D2).

No MCC, aplicação, resgate, saque e depósito entre as próprias contas eram lançados como uma despesa numa conta e
uma receita na outra (e às vezes só um dos lados). No Finora isso é movimentação, fora da DRE:

- **par** (despesa numa conta + receita de mesmo valor em outra, pagas com até `DAYS` dias de diferença) vira uma
  **transferência**: a despesa passa a ser a transferência e a receita sai (o vínculo com o MCC vai junto, para a
  reimportação não trazer de volta);
- **avulso** (só um lado): despesa vira **retirada** e receita vira **depósito** (ajuste de saldo).

O saldo das contas não muda; só a DRE deixa de contar esse dinheiro como receita/despesa.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from finora.models import Account, Attachment, BankLine, Category, Entry, ImportMap

DAYS = 3
WORDS = "aplicacao, resgate, saque, deposito, transferencia"


def _plain(text: str | None) -> str:
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


def parse_words(text: str) -> list[str]:
    """"aplicação, resgate" -> ["aplica", "resgat"]: o começo de cada palavra (pega plural e variações)."""
    out = []
    for w in (_plain(x) for x in (text or "").split(",")):
        if w:
            out.append(w[:6] if len(w) > 6 else w)
    return out


@dataclass(frozen=True)
class Move:
    """Uma proposta: par (expense_id + income_id) ou avulso (só um dos dois)."""
    day: date
    amount: Decimal
    description: str
    from_account: str | None       # de onde sai o dinheiro (despesa)
    to_account: str | None         # para onde vai (receita)
    expense_id: int | None
    income_id: int | None

    @property
    def kind(self) -> str:
        if self.expense_id and self.income_id:
            return "transfer"
        return "withdrawal" if self.expense_id else "deposit"

    @property
    def kind_label(self) -> str:
        return {"transfer": "Transferência", "withdrawal": "Retirada", "deposit": "Depósito"}[self.kind]

    @property
    def key(self) -> tuple[int | None, int | None]:
        return self.expense_id, self.income_id


def find(s: Session, entity_id: int, words: str = WORDS, days: int = DAYS) -> list[Move]:
    """Receitas/despesas pagas cuja categoria (o "item" do MCC) tem uma das palavras: os pares viram transferência,
    o resto fica avulso. Mais antigo primeiro."""
    keys = parse_words(words)
    if not keys:
        return []
    names = dict(s.execute(select(Account.id, Account.name)).all())
    rows = s.execute(select(Entry, Category.name).join(Category, Entry.category_id == Category.id)
                     .where(Entry.entity_id == entity_id, Entry.kind.in_(("income", "expense")),
                            Entry.status == "paid", Entry.paid_date.is_not(None))
                     .order_by(Entry.paid_date, Entry.id)).all()
    hits = [e for e, cat in rows if any(k in _plain(cat) for k in keys)]
    incomes = [e for e in hits if e.kind == "income"]
    used: set[int] = set()
    out = []
    for e in (x for x in hits if x.kind == "expense"):
        pair = next((i for i in incomes if i.id not in used and i.account_id != e.account_id
                     and Decimal(i.amount) == Decimal(e.amount) and abs((i.paid_date - e.paid_date).days) <= days),
                    None)
        if pair is not None:
            used.add(pair.id)
            out.append(Move(e.paid_date, Decimal(e.amount), e.description or "", names.get(e.account_id),
                            names.get(pair.account_id), e.id, pair.id))
        else:
            out.append(Move(e.paid_date, Decimal(e.amount), e.description or "", names.get(e.account_id), None,
                            e.id, None))
    for i in incomes:
        if i.id not in used:
            out.append(Move(i.paid_date, Decimal(i.amount), i.description or "", None, names.get(i.account_id),
                            None, i.id))
    out.sort(key=lambda m: (m.day, m.kind != "transfer", m.expense_id or m.income_id))
    return out


def _bare(e: Entry, kind: str) -> None:
    e.kind = kind
    e.category_id = e.contact_id = e.cost_center_id = None
    e.original_amount = None


def convert(s: Session, entity_id: int, moves: list[Move]) -> dict[str, int]:
    """Aplica as propostas escolhidas. Devolve quantas viraram transferência, retirada e depósito."""
    from finora.services import audit, period_lock
    done = {"transfer": 0, "withdrawal": 0, "deposit": 0}
    for m in moves:
        exp = s.get(Entry, m.expense_id) if m.expense_id else None
        inc = s.get(Entry, m.income_id) if m.income_id else None
        for e, kind in ((exp, "expense"), (inc, "income")):
            if (e is None) != (getattr(m, f"{kind}_id") is None) or (e is not None and
                                                                    (e.kind != kind or e.entity_id != entity_id)):
                raise ValueError("Um dos lançamentos mudou desde a busca. Procure de novo.")
            if e is not None and period_lock.is_locked(s, entity_id, e.competence_date):
                raise ValueError(f"\"{e.description}\" de {e.competence_date:%d/%m/%Y} está num período fechado: "
                                 "reabra o período em Configurações para converter.")
        if exp is not None and inc is not None:
            _bare(exp, "transfer")
            exp.dest_account_id = inc.account_id
            if inc.notes and inc.notes != exp.notes:
                exp.notes = "\n".join(x for x in (exp.notes, inc.notes) if x)
            s.execute(update(ImportMap).where(ImportMap.target == str(inc.id),
                                              ImportMap.kind == "lancamentos")
                      .values(target=str(exp.id)))          # reimportar o MCC não traz a receita de volta
            s.execute(update(Attachment).where(Attachment.entry_id == inc.id).values(entry_id=exp.id))
            s.execute(update(BankLine).where(BankLine.entry_id == inc.id).values(entry_id=exp.id))
            s.execute(delete(Entry).where(Entry.id == inc.id))
        else:
            _bare(exp or inc, "withdrawal" if exp is not None else "deposit")
        done[m.kind] += 1
    s.commit()
    if any(done.values()):
        audit.note(s, entity_id, "Movimentação lançada como receita/despesa (D2): "
                                 f"{done['transfer']} transferência(s), {done['withdrawal']} retirada(s) e "
                                 f"{done['deposit']} depósito(s).")
    return done
