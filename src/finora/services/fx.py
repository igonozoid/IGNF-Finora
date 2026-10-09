"""Multimoeda: cotações com histórico por data e conversão para a moeda principal.

Cada lançamento guarda `amount` (na moeda da conta) e `base_amount` (na moeda principal, pela cotação da data
de competência). Os relatórios que juntam contas somam `base_amount`; o saldo e o extrato de cada conta usam
`amount`. O `base_amount` é calculado sozinho ao gravar (gancho before_flush abaixo) e recalculado quando uma
cotação muda. Sem cotação cadastrada, vale 1 para 1 (e o app avisa em Configurações › Moedas).
"""
import bisect
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from finora.core import money
from finora.models import Account, Entity, Entry, ExchangeRate

CENT = Decimal("0.01")
# moedas com PTAX no Banco Central (as outras: cotação digitada)
BCB_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "CHF", "JPY", "DKK", "NOK", "SEK"}


class Converter:
    """Converte valores para a moeda principal de uma entidade, usando as cotações cadastradas."""

    def __init__(self, s: Session, entity_id: int):
        self.base = s.get(Entity, entity_id).currency
        self.rates: dict[str, tuple[list[date], list[Decimal]]] = {}
        q = (select(ExchangeRate.currency, ExchangeRate.day, ExchangeRate.rate)
             .where(ExchangeRate.entity_id == entity_id).order_by(ExchangeRate.currency, ExchangeRate.day))
        for cur, day, rate in s.execute(q):
            days, values = self.rates.setdefault(cur, ([], []))
            days.append(day)
            values.append(Decimal(rate))

    def rate(self, currency: str, day: date) -> Decimal | None:
        """A cotação vigente no dia (a última até ele; se não houver anterior, a primeira depois)."""
        if currency == self.base:
            return Decimal(1)
        if currency not in self.rates:
            return None
        days, values = self.rates[currency]
        i = bisect.bisect_right(days, day) - 1
        return values[max(i, 0)]

    def convert(self, amount: Decimal, currency: str, day: date) -> Decimal:
        rate = self.rate(currency, day)
        value = Decimal(amount) * (rate if rate is not None else 1)
        return value.quantize(CENT, rounding=ROUND_HALF_UP)

    def missing(self, currency: str) -> bool:
        return currency != self.base and currency not in self.rates


# ---------- base_amount sozinho ao gravar ----------
@event.listens_for(Session, "before_flush")
def _fill_base_amount(s: Session, _ctx, _instances) -> None:
    pending = [o for o in list(s.new) + list(s.dirty) if isinstance(o, Entry)]
    if not pending:
        return
    converters: dict[int, Converter] = {}
    for e in pending:
        if e.amount is None or e.account_id is None:
            continue
        acc = s.get(Account, e.account_id)
        day = e.competence_date or e.due_date or date.today()
        if acc is None or acc.entity_id is None:
            e.base_amount = e.amount
            continue
        conv = converters.get(acc.entity_id) or converters.setdefault(acc.entity_id, Converter(s, acc.entity_id))
        e.base_amount = conv.convert(e.amount, acc.currency, day)


def recompute(s: Session, entity_id: int, currency: str | None = None) -> int:
    """Recalcula o base_amount dos lançamentos (de uma moeda, ou todos). Retorna quantos mudaram."""
    conv = Converter(s, entity_id)
    q = (select(Entry, Account.currency).join(Account, Entry.account_id == Account.id)
         .where(Entry.entity_id == entity_id))
    if currency:
        q = q.where(Account.currency == currency)
    n = 0
    for e, cur in s.execute(q):
        value = conv.convert(e.amount, cur, e.competence_date)
        if e.base_amount != value:
            e.base_amount = value
            n += 1
    s.commit()
    return n


# ---------- cotações ----------
@dataclass(frozen=True)
class RateView:
    id: int
    currency: str
    day: date
    rate: Decimal
    source: str


@dataclass(frozen=True)
class CurrencyStatus:
    currency: str
    accounts: int                # contas nessa moeda
    latest: RateView | None
    entries_without_rate: int    # lançamentos que ficaram 1 para 1 por falta de cotação


def base_currency(s: Session, entity_id: int) -> str:
    return s.get(Entity, entity_id).currency


def foreign_currencies(s: Session, entity_id: int) -> list[str]:
    """Moedas (diferentes da principal) usadas em contas ou com cotação cadastrada."""
    base = base_currency(s, entity_id)
    used = set(s.scalars(select(Account.currency).where(Account.entity_id == entity_id)))
    used |= set(s.scalars(select(ExchangeRate.currency).where(ExchangeRate.entity_id == entity_id)))
    return sorted(c for c in used if c != base)


def status(s: Session, entity_id: int) -> list[CurrencyStatus]:
    out = []
    conv = Converter(s, entity_id)
    for cur in foreign_currencies(s, entity_id):
        n_acc = s.scalar(select(func.count(Account.id)).where(Account.entity_id == entity_id, Account.currency == cur))
        rates = list_rates(s, entity_id, cur)
        without = 0
        if conv.missing(cur):
            without = s.scalar(select(func.count(Entry.id)).join(Account, Entry.account_id == Account.id)
                               .where(Entry.entity_id == entity_id, Account.currency == cur))
        out.append(CurrencyStatus(cur, n_acc, rates[0] if rates else None, without))
    return out


def list_rates(s: Session, entity_id: int, currency: str, limit: int = 60) -> list[RateView]:
    """Mais recentes primeiro."""
    q = (select(ExchangeRate).where(ExchangeRate.entity_id == entity_id, ExchangeRate.currency == currency)
         .order_by(ExchangeRate.day.desc()).limit(limit))
    return [RateView(r.id, r.currency, r.day, Decimal(r.rate), r.source) for r in s.scalars(q)]


def set_rate(s: Session, entity_id: int, currency: str, day: date, rate: Decimal, source: str = "manual") -> int:
    """Grava (ou corrige) a cotação do dia e recalcula os lançamentos dessa moeda."""
    base = base_currency(s, entity_id)
    if currency == base:
        raise ValueError("A moeda principal não precisa de cotação.")
    if currency not in money.CURRENCIES:
        raise ValueError(f"Moeda não suportada: {currency}")
    if rate is None or rate <= 0:
        raise ValueError("A cotação precisa ser maior que zero.")
    from finora.services import period_lock
    lock = period_lock.locked_through(s, entity_id)
    if lock and day <= lock:
        raise ValueError(f"O período até {lock:%d/%m/%Y} está fechado: cadastre cotações de datas depois dele.")
    r = s.scalar(select(ExchangeRate).where(ExchangeRate.entity_id == entity_id, ExchangeRate.currency == currency,
                                            ExchangeRate.day == day))
    if r is None:
        r = ExchangeRate(entity_id=entity_id, currency=currency, day=day)
        s.add(r)
    r.rate, r.source = rate, source
    s.commit()
    recompute(s, entity_id, currency)
    return r.id


def delete_rate(s: Session, rate_id: int) -> None:
    r = s.get(ExchangeRate, rate_id)
    if r is None:
        return
    entity_id, currency = r.entity_id, r.currency
    from finora.services import period_lock
    if period_lock.is_locked(s, entity_id, r.day):
        raise ValueError("Essa cotação é de um período fechado e não pode ser excluída.")
    s.delete(r)
    s.commit()
    recompute(s, entity_id, currency)


def latest_rates(s: Session, entity_id: int) -> dict[str, Decimal]:
    """Cotação mais recente de cada moeda (para o saldo de hoje)."""
    conv = Converter(s, entity_id)
    return {cur: values[-1] for cur, (_days, values) in conv.rates.items()}


def to_base_today(s: Session, entity_id: int, amount: Decimal, currency: str) -> Decimal:
    conv = Converter(s, entity_id)
    return conv.convert(amount, currency, date.today())


# ---------- PTAX do Banco Central (só quando a moeda principal é o real) ----------
def fetch_bcb(currency: str, day: date, timeout: float = 10) -> tuple[date, Decimal]:
    """Cotação PTAX de venda do Banco Central no dia (ou no último dia útil antes dele).
    Levanta ValueError com mensagem pronta (sem internet, moeda sem PTAX…)."""
    import requests
    from datetime import timedelta
    if currency not in BCB_CURRENCIES:
        raise ValueError(f"O Banco Central não publica cotação para {currency}.")
    url = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
           "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)")
    start = day - timedelta(days=10)
    params = {"@moeda": f"'{currency}'", "@dataInicial": f"'{start:%m-%d-%Y}'",
              "@dataFinalCotacao": f"'{day:%m-%d-%Y}'", "$format": "json",
              "$select": "cotacaoVenda,dataHoraCotacao,tipoBoletim"}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json().get("value", [])
    except Exception as exc:
        raise ValueError("Não consegui buscar a cotação no Banco Central. Confira a internet ou digite a "
                         "cotação à mão.") from exc
    closing = [r for r in rows if r.get("tipoBoletim") == "Fechamento"] or rows
    if not closing:
        raise ValueError("O Banco Central não tem cotação para esse período.")
    last = closing[-1]
    when = date.fromisoformat(last["dataHoraCotacao"][:10])
    return when, Decimal(str(last["cotacaoVenda"])).quantize(Decimal("0.00000001"))
