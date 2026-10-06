from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, cards, categories, dashboard, entries, reports
from finora.services.entries import EntryData

TODAY = date(2026, 10, 15)


# ---------- datas da fatura ----------
@pytest.mark.parametrize("purchase, closing, due", [
    (date(2026, 10, 10), date(2026, 10, 25), date(2026, 11, 5)),    # antes do fechamento
    (date(2026, 10, 24), date(2026, 10, 25), date(2026, 11, 5)),
    (date(2026, 10, 25), date(2026, 11, 25), date(2026, 12, 5)),    # NO dia do fechamento: próxima
    (date(2026, 10, 31), date(2026, 11, 25), date(2026, 12, 5)),
    (date(2026, 12, 28), date(2027, 1, 25), date(2027, 2, 5)),      # virada de ano
])
def test_fatura_fecha_25_vence_5(purchase, closing, due):
    assert cards.statement_for(purchase, 25, 5) == (closing, due)


def test_fatura_que_vence_no_mesmo_mes_e_mes_curto():
    assert cards.statement_for(date(2026, 10, 3), 5, 15) == (date(2026, 10, 5), date(2026, 10, 15))
    assert cards.statement_for(date(2026, 10, 5), 5, 15) == (date(2026, 11, 5), date(2026, 11, 15))
    # fecha dia 31: em fevereiro fecha no último dia
    assert cards.statement_for(date(2027, 2, 10), 31, 10) == (date(2027, 2, 28), date(2027, 3, 10))


# ---------- cenário ----------
@pytest.fixture
def ctx(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    card = accounts.create(s, eid, name="Itaú", kind="card", opening_balance=D(0),
                           closing_day=25, due_day=5, credit_limit=D("2000"))
    exp = {label: cid for cid, label in categories.choices(s, eid, "expense")}

    def buy(desc, amount, day, **kw):
        return entries.create(s, eid, EntryData(kind="expense", description=desc, amount=D(amount), due_date=day,
                                                account_id=card, category_id=exp["Alimentação › Supermercado"],
                                                **kw))
    return dict(s=s, eid=eid, bank=bank, card=card, buy=buy)


def test_cartao_valida_dias(session, profile):
    with pytest.raises(ValueError):
        accounts.create(session, profile.id, name="X", kind="card", opening_balance=D(0), closing_day=25)
    with pytest.raises(ValueError):
        accounts.create(session, profile.id, name="X", kind="card", opening_balance=D(0), closing_day=32, due_day=5)
    with pytest.raises(ValueError):
        accounts.create(session, profile.id, name="X", kind="card", opening_balance=D(0), closing_day=5, due_day=5)
    acc_id = accounts.create(session, profile.id, name="Conta", kind="bank", opening_balance=D(0),
                             closing_day=25, due_day=5)            # só cartão guarda esses dias
    acc = next(a for a in accounts.list_accounts(session, profile.id) if a.id == acc_id)
    assert (acc.closing_day, acc.due_day, acc.card_info) == (None, None, "")


def test_compra_vai_para_a_fatura_certa(ctx):
    (i,) = ctx["buy"]("Mercado", "300", date(2026, 10, 10))
    e = entries.get(ctx["s"], i)
    assert e.on_card and e.status_label(TODAY) == "No cartão" and not e.is_late(date(2027, 1, 1))
    assert (e.competence_date, e.due_date) == (date(2026, 10, 10), date(2026, 11, 5))
    saldos = {a.name: a.balance for a in accounts.list_accounts(ctx["s"], ctx["eid"])}
    assert saldos["Itaú"] == D("-300.00") and saldos["Banco"] == D("100.00")   # o banco só paga na fatura
    assert cards.available_limit(ctx["s"], ctx["card"]) == D("1700.00")
    # não aparece como "a pagar" sozinha; a fatura é que aparece nos totais
    nov = entries.list_entries(ctx["s"], ctx["eid"], year=2026, month=11, filter="payable", today=TODAY)
    assert nov == []
    assert entries.month_totals(ctx["s"], ctx["eid"], 2026, 11).payable == D("300.00")
    with pytest.raises(ValueError, match="fatura"):
        entries.set_paid(ctx["s"], i, True)


def test_parcelado_no_cartao_cai_em_faturas_seguidas(ctx):
    ids = ctx["buy"]("TV", "1200", date(2026, 10, 20), repeat="installments", times=3)
    dues = [entries.get(ctx["s"], i).due_date for i in ids]
    assert dues == [date(2026, 11, 5), date(2026, 12, 5), date(2027, 1, 5)]
    sts = cards.list_statements(ctx["s"], ctx["card"], TODAY)
    assert [(st.due, st.charges) for st in sts if st.charges] == [
        (date(2027, 1, 5), D("400.00")), (date(2026, 12, 5), D("400.00")), (date(2026, 11, 5), D("400.00"))]


def test_fatura_estorno_pagamento_e_situacao(ctx):
    s, card = ctx["s"], ctx["card"]
    ctx["buy"]("Mercado", "500", date(2026, 10, 10))
    entries.create(s, ctx["eid"], EntryData(kind="income", description="Estorno", amount=D("50"),
                                            due_date=date(2026, 10, 12), account_id=card))
    st = cards.statement(s, card, date(2026, 11, 5))
    assert (st.charges, st.remaining, st.entries) == (D("450.00"), D("450.00"), 2)
    assert st.status(TODAY) == "open"                                   # ainda não fechou (fecha 25/10)
    assert st.status(date(2026, 10, 26)) == "closed"
    assert st.status(date(2026, 11, 6)) == "late"
    cards.pay(s, card, st.due, from_account_id=ctx["bank"], amount=D("200"), when=date(2026, 11, 3))
    st = cards.statement(s, card, st.due)
    assert (st.paid, st.remaining, st.status(date(2026, 11, 6))) == (D("200.00"), D("250.00"), "late")
    cards.pay(s, card, st.due, from_account_id=ctx["bank"], amount=D("250"), when=date(2026, 11, 4))
    st = cards.statement(s, card, st.due)
    assert st.status(date(2026, 11, 6)) == "paid"
    saldos = {a.name: a.balance for a in accounts.list_accounts(s, ctx["eid"])}
    assert saldos["Itaú"] == D("0.00") and saldos["Banco"] == D("-350.00")   # 100 - 450
    with pytest.raises(ValueError):
        cards.pay(s, card, st.due, from_account_id=card, amount=D("1"))


def test_fatura_nos_relatorios_e_no_dashboard(ctx):
    s, eid = ctx["s"], ctx["eid"]
    ctx["buy"]("Mercado", "300", date(2026, 10, 10))                    # fatura vence 05/11
    # DRE competência: no mês da compra; DRE caixa: no mês do vencimento da fatura
    comp = reports.dre(s, eid, [(2026, 10), (2026, 11)], "accrual")
    caixa = reports.dre(s, eid, [(2026, 10), (2026, 11)], "cash")
    assert comp.row("alimentacao").values == [D("-300.00"), D("0.00")]
    assert caixa.row("alimentacao").values == [D("0.00"), D("-300.00")]
    # fluxo de caixa: a fatura é uma saída única no vencimento
    flow = reports.cash_flow(s, eid, 30, TODAY)
    day = next(d for d in flow.days if d.day == date(2026, 11, 5))
    assert day.outflow == D("300.00") and day.items == ["Fatura Itaú nov/2026"]
    # dashboard: fatura conta em "a pagar (30 dias)"
    k = dashboard.kpis(s, eid, TODAY)
    assert k.payable == D("300.00") and k.payable_n == 1


def test_editar_compra_muda_de_fatura_e_cartao_sem_configuracao(ctx, session, profile):
    s = ctx["s"]
    (i,) = ctx["buy"]("Mercado", "100", date(2026, 10, 10))
    entries.update(s, i, EntryData(kind="expense", description="Mercado", amount=D("120"),
                                   due_date=date(2026, 10, 26), account_id=ctx["card"]))
    e = entries.get(s, i)
    assert (e.amount, e.competence_date, e.due_date) == (D("120.00"), date(2026, 10, 26), date(2026, 12, 5))
    # cartão sem fechamento/vencimento: funciona como conta comum (lançamento a pagar)
    old = accounts.create(s, ctx["eid"], name="Antigo", kind="card", opening_balance=D(0))
    (j,) = entries.create(s, ctx["eid"], EntryData(kind="expense", description="X", amount=D("10"),
                                                   due_date=date(2026, 10, 10), account_id=old))
    assert entries.get(s, j).status == "pending" and cards.list_statements(s, old, TODAY) == []


def test_compras_da_fatura_e_faturas_do_periodo(ctx):
    s = ctx["s"]
    ctx["buy"]("Padaria", "20", date(2026, 10, 12))
    ctx["buy"]("Mercado", "300", date(2026, 10, 10))
    ctx["buy"]("Depois do fechamento", "50", date(2026, 10, 26))
    assert [e.description for e in cards.statement_entries(s, ctx["card"], date(2026, 11, 5))] == ["Mercado", "Padaria"]
    sts = cards.due_between(s, ctx["eid"], date(2026, 11, 1), date(2026, 11, 30), TODAY)
    assert [(st.account, st.due, st.charges) for st in sts] == [("Itaú", date(2026, 11, 5), D("320.00"))]


def test_saldo_em_contas_nao_desconta_o_cartao_duas_vezes(ctx):
    s, eid = ctx["s"], ctx["eid"]
    ctx["buy"]("Notebook", "3000", date(2026, 10, 10), repeat="installments", times=3)   # 1.000 por fatura
    lst = accounts.list_accounts(s, eid)
    assert accounts.total_balance(lst) == D("100.00")             # só o banco; o cartão não entra
    assert next(a for a in lst if a.name == "Itaú").balance == D("-3000.00")   # dívida aparece no cartão
    flow = reports.cash_flow(s, eid, 30, TODAY)
    assert flow.start_balance == D("100.00")
    assert flow.outflow == D("1000.00")                           # só a fatura que vence no período
    assert flow.end_balance == D("-900.00")
    assert dashboard.kpis(s, eid, TODAY).balance == D("100.00")


def test_faturas_futuras_e_sem_meses_vazios(ctx):
    ctx["buy"]("TV", "1200", date(2026, 10, 20), repeat="installments", times=3)
    sts = cards.list_statements(ctx["s"], ctx["card"], TODAY, back=6)
    assert [st.due for st in sts] == [date(2027, 1, 5), date(2026, 12, 5), date(2026, 11, 5)]   # nada vazio
    assert [st.status(TODAY) for st in sts] == ["future", "future", "open"]
    assert sts[0].status_label(TODAY) == "Futura"
