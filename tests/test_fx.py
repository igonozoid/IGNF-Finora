from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, dashboard, entries, fx, reports
from finora.services.entries import EntryData


@pytest.fixture
def plus_session(session, plus):
    return session


def _usd_account(s, eid, balance="100"):
    return accounts.create(s, eid, name="Conta EUA", kind="bank", opening_balance=D(balance), currency="USD")


def _expense(s, eid, acc, amount, when, desc="Hotel"):
    return entries.create(s, eid, EntryData(kind="expense", description=desc, amount=D(amount), due_date=when,
                                            account_id=acc))[0]


def test_valor_convertido_pela_cotacao_da_data(plus_session, profile):
    s, eid = plus_session, profile.id
    usd = _usd_account(s, eid)
    fx.set_rate(s, eid, "USD", date(2026, 9, 1), D("5.00"))
    fx.set_rate(s, eid, "USD", date(2026, 10, 1), D("5.50"))
    sep = _expense(s, eid, usd, "10", date(2026, 9, 15))
    oct_ = _expense(s, eid, usd, "10", date(2026, 10, 15))
    assert entries.get(s, sep).base_amount == D("50.00") and entries.get(s, oct_).base_amount == D("55.00")
    # a DRE soma na moeda principal
    rep = reports.dre(s, eid, [(2026, 9), (2026, 10)])
    total = next(r for r in rep.rows if r.key == "outras")
    assert total.values == [D("-50.00"), D("-55.00")]
    # corrigir uma cotação recalcula os lançamentos daquele período
    fx.set_rate(s, eid, "USD", date(2026, 9, 1), D("4.00"))
    assert entries.get(s, sep).base_amount == D("40.00") and entries.get(s, oct_).base_amount == D("55.00")
    rid = fx.list_rates(s, eid, "USD")[0].id                     # a de outubro (mais recente primeiro)
    fx.delete_rate(s, rid)
    assert entries.get(s, oct_).base_amount == D("40.00")         # volta a valer a de setembro


def test_saldo_total_converte_contas_em_outra_moeda(plus_session, profile):
    s, eid = plus_session, profile.id
    _usd_account(s, eid, "100")
    accs = accounts.list_accounts(s, eid)
    assert accounts.total_balance(accs) == D("200.00")           # sem cotação: 1 para 1 (avisado em Moedas)
    st = fx.status(s, eid)
    assert [(c.currency, c.accounts, c.latest) for c in st] == [("USD", 1, None)]
    fx.set_rate(s, eid, "USD", date(2026, 1, 1), D("5"))
    accs = accounts.list_accounts(s, eid)
    usd = next(a for a in accs if a.currency == "USD")
    assert (usd.balance, usd.base_balance) == (D("100"), D("500.00"))
    assert accounts.total_balance(accs) == D("600.00")
    assert dashboard.kpis(s, eid).balance == D("600.00")


def test_transferencia_entre_moedas(plus_session, profile):
    s, eid = plus_session, profile.id
    brl = accounts.list_accounts(s, eid)[0].id
    usd = _usd_account(s, eid, "0")
    with pytest.raises(ValueError, match="quanto chega"):
        entries.create(s, eid, EntryData(kind="transfer", description="Câmbio", amount=D("550"),
                                         due_date=date(2026, 10, 1), account_id=brl, dest_account_id=usd, paid=True))
    entries.create(s, eid, EntryData(kind="transfer", description="Câmbio", amount=D("550"),
                                     due_date=date(2026, 10, 1), account_id=brl, dest_account_id=usd, paid=True,
                                     dest_amount=D("100")))
    by = {a.currency: a for a in accounts.list_accounts(s, eid)}
    assert by["BRL"].balance == D("-450.00") and by["USD"].balance == D("100")
    st = reports.account_statement(s, usd, date(2026, 10, 1), date(2026, 10, 31))
    assert st.lines[0].inflow == D("100")


def test_cartao_fica_na_moeda_principal(plus_session, profile):
    with pytest.raises(ValueError, match="moeda principal"):
        accounts.create(plus_session, profile.id, name="Visa", kind="card", opening_balance=D("0"), currency="USD")


def test_validacoes_de_cotacao(plus_session, profile):
    s, eid = plus_session, profile.id
    with pytest.raises(ValueError, match="principal"):
        fx.set_rate(s, eid, "BRL", date(2026, 1, 1), D("1"))
    with pytest.raises(ValueError, match="maior que zero"):
        fx.set_rate(s, eid, "USD", date(2026, 1, 1), D("0"))


def test_ptax_do_banco_central(monkeypatch):
    import requests

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"value": [
                {"cotacaoVenda": 5.4321, "dataHoraCotacao": "2026-10-02 13:05:00.000", "tipoBoletim": "Intermediário"},
                {"cotacaoVenda": 5.4567, "dataHoraCotacao": "2026-10-02 13:10:00.000", "tipoBoletim": "Fechamento"}]}

    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    assert fx.fetch_bcb("USD", date(2026, 10, 4)) == (date(2026, 10, 2), D("5.45670000"))

    def offline(*a, **k):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(requests, "get", offline)
    with pytest.raises(ValueError, match="internet"):
        fx.fetch_bcb("USD", date(2026, 10, 4))
    with pytest.raises(ValueError, match="não publica"):
        fx.fetch_bcb("BRL", date(2026, 10, 4))
