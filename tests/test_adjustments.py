"""Ajuste de saldo (depósito/retirada, as movimentações bancárias D/R do MCC): mexe no saldo, no extrato, na previsão
de caixa e na conciliação; fica fora da DRE e dos relatórios de resultado."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, categories, dashboard, entries, reconcile, receipts, reports
from finora.services.entries import EntryData

TODAY = date(2026, 10, 15)


@pytest.fixture
def ctx(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id                  # saldo inicial R$ 100,00
    cash = accounts.create(s, eid, name="Caixa", kind="cash", opening_balance=D(0))
    luz = dict((label, cid) for cid, label in categories.choices(s, eid, "expense"))["Moradia › Luz"]
    return dict(s=s, eid=eid, bank=bank, cash=cash, luz=luz)


def _add(c, kind, amount, when=date(2026, 10, 5), paid=True, account=None, **kw):
    return entries.create(c["s"], c["eid"], EntryData(kind=kind, description=kw.pop("description", kind),
                                                      amount=D(amount), due_date=when,
                                                      account_id=account or c["bank"], paid=paid,
                                                      paid_date=when if paid else None, **kw))[0]


def test_deposito_e_retirada_mexem_no_saldo_e_no_extrato(ctx):
    s = ctx["s"]
    dep = _add(ctx, "deposit", "1500", description="Aporte dos sócios", contact="Ignorado", category_id=ctx["luz"])
    _add(ctx, "withdrawal", "300", when=date(2026, 10, 6), description="Saque para o caixa")
    e = entries.get(s, dep)
    assert e.category is None and e.contact is None and e.signed_amount == D("1500")        # sem categoria/contato
    assert e.status_label(TODAY) == "Depositado"
    bal = {a.id: a.balance for a in accounts.list_accounts(s, ctx["eid"])}
    assert bal[ctx["bank"]] == D("1300.00")                                                  # 100 + 1500 - 300
    st = reports.account_statement(s, ctx["bank"], date(2026, 10, 1), date(2026, 10, 31))
    assert [(x.category, x.inflow, x.outflow) for x in st.lines] == \
        [("Depósito", D("1500"), D("0")), ("Retirada", D("0"), D("300"))]
    assert st.closing == D("1300.00")


def test_fora_da_dre_e_dos_relatorios_de_resultado(ctx):
    s, eid = ctx["s"], ctx["eid"]
    _add(ctx, "deposit", "1500")
    _add(ctx, "withdrawal", "300")
    _add(ctx, "expense", "120", category_id=ctx["luz"], description="Luz")
    dre = reports.dre(s, eid, [(2026, 10)])
    assert sum(r.values[0] for r in dre.rows if r.style == "line") == D("-120.00")           # só a luz
    assert [c.category for c in reports.by_category(s, eid, date(2026, 10, 1), date(2026, 10, 31))] == ["Luz"]
    assert [e.description for e in reports.analytical(s, eid, date(2026, 10, 1), date(2026, 10, 31))] == ["Luz"]
    assert dashboard.month_result(s, eid, 2026, 10) == D("-120.00")
    t = entries.month_totals(s, eid, 2026, 10)
    assert t.payable == D("0") and t.receivable == D("0")


def test_previsto_entra_na_previsao_de_caixa_mas_nao_no_a_pagar(ctx):
    s, eid = ctx["s"], ctx["eid"]
    _add(ctx, "withdrawal", "40", when=date(2026, 10, 20), paid=False, description="Retirada programada")
    flow = reports.cash_flow(s, eid, days=10, today=TODAY)
    assert flow.start_balance == D("100.00") and flow.end_balance == D("60.00")
    assert reports.agenda(s, eid, date(2026, 10, 1), date(2026, 10, 31)) == []               # não é conta a pagar
    e = entries.list_entries(s, eid, year=2026, month=10, today=TODAY)[0]
    assert e.status_label(TODAY) == "A retirar"
    entries.pay(s, e.id, date(2026, 10, 20), note="feita no banco")                          # baixa: só a data
    with pytest.raises(ValueError, match="só a data"):
        entries.pay(s, _add(ctx, "deposit", "10", paid=False), amount=D("11"))


def test_filtro_recibo_cartao_e_conciliacao(ctx):
    s, eid = ctx["s"], ctx["eid"]
    dep = _add(ctx, "deposit", "500")
    _add(ctx, "expense", "50", category_id=ctx["luz"])
    names = [e.kind for e in entries.list_entries(s, eid, year=2026, month=10, kind="adjust")]
    assert names == ["deposit"]
    assert "não têm recibo" in receipts.can_issue(s.get(entries.Entry, dep))
    card = accounts.create(s, eid, name="Visa", kind="card", opening_balance=D(0), closing_day=25, due_day=5)
    with pytest.raises(ValueError, match="cartão"):
        _add(ctx, "withdrawal", "10", account=card)
    reconcile.import_lines(s, eid, ctx["bank"], [reconcile.OfxLine("D1", date(2026, 10, 5), D("500.00"), "DEPOSITO")])
    line = reconcile.lines(s, eid, ctx["bank"], show="all")[0]
    assert line.status == "matched" and line.entry_id == dep                                  # casou com o depósito
