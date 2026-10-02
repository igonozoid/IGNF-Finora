from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, categories, entries, reports
from finora.services.entries import EntryData

TODAY = date(2026, 10, 15)


@pytest.fixture
def ctx(session, profile):
    exp = {label: cid for cid, label in categories.choices(session, profile.id, "expense")}
    inc = {label: cid for cid, label in categories.choices(session, profile.id, "income")}
    bank = accounts.list_accounts(session, profile.id)[0].id

    def add(desc, amount, due, cat=None, kind="expense", paid=False, paid_date=None, **kw):
        cid = (inc if kind == "income" else exp).get(cat) if cat else None
        return entries.create(session, profile.id, EntryData(
            kind=kind, description=desc, amount=D(amount), due_date=due, account_id=bank, category_id=cid,
            paid=paid, paid_date=paid_date, **kw))

    return dict(s=session, eid=profile.id, bank=bank, add=add)


def test_periodos():
    assert reports.period_months("3m", TODAY) == [(2026, 8), (2026, 9), (2026, 10)]
    assert reports.period_months("ytd", TODAY)[0] == (2026, 1) and len(reports.period_months("ytd", TODAY)) == 10
    assert reports.period_months("last_year", TODAY) == [(2025, m) for m in range(1, 13)]
    assert reports.period_months("12m", date(2026, 3, 1))[0] == (2025, 4)


def test_dre_competencia(ctx):
    add = ctx["add"]
    add("Salário", "5000", date(2026, 9, 5), "Receitas › Salário", kind="income", paid=True)
    add("Salário", "5000", date(2026, 10, 5), "Receitas › Salário", kind="income")
    add("Aluguel", "1500", date(2026, 10, 8), "Moradia › Aluguel ou financiamento")
    add("Luz", "200", date(2026, 10, 9), "Moradia › Luz")
    add("Mercado", "800", date(2026, 10, 12), "Alimentação › Supermercado")
    add("Sem categoria", "100", date(2026, 10, 12))
    add("Presente recebido", "50", date(2026, 10, 12), kind="income")
    add("Reserva", "1000", date(2026, 10, 20), "Investimentos/Reserva › Reserva de emergência")
    rep = reports.dre(ctx["s"], ctx["eid"], [(2026, 9), (2026, 10)])
    v = {r.key: r.values for r in rep.rows}
    assert v["receitas"] == [D("5000.00"), D("5050.00")]
    assert v["moradia"] == [D("0.00"), D("-1700.00")]
    assert v["outras"][1] == D("-100.00")                    # despesa sem categoria
    assert v["sobra"] == [D("5000.00"), D("2450.00")]
    assert v["investimentos"][1] == D("-1000.00")
    assert v["livre"] == [D("5000.00"), D("1450.00")]
    assert rep.row("livre").total == D("6450.00")
    assert rep.share(rep.row("moradia")) == D("16.9")         # 1700 / 10050


def test_dre_caixa_usa_data_do_pagamento(ctx):
    add = ctx["add"]
    add("Aluguel set", "1500", date(2026, 9, 8), "Moradia › Aluguel ou financiamento",
        paid=True, paid_date=date(2026, 10, 2))                      # venceu em set, pago em out
    add("Luz", "200", date(2026, 10, 9), "Moradia › Luz")             # não pago: fora do caixa
    caixa = reports.dre(ctx["s"], ctx["eid"], [(2026, 9), (2026, 10)], regime="cash")
    comp = reports.dre(ctx["s"], ctx["eid"], [(2026, 9), (2026, 10)], regime="accrual")
    assert caixa.row("moradia").values == [D("0.00"), D("-1500.00")]
    assert comp.row("moradia").values == [D("-1500.00"), D("-200.00")]


def test_dre_detalhes_e_transferencia(ctx):
    add = ctx["add"]
    add("Aluguel", "1500", date(2026, 10, 8), "Moradia › Aluguel ou financiamento")
    add("Luz", "200", date(2026, 10, 9), "Moradia › Luz")
    cash = accounts.create(ctx["s"], ctx["eid"], name="Carteira", kind="cash", opening_balance=D(0))
    entries.create(ctx["s"], ctx["eid"], EntryData(kind="transfer", description="Saque", amount=D("300"),
                                                   due_date=date(2026, 10, 3), account_id=ctx["bank"],
                                                   dest_account_id=cash))
    rep = reports.dre(ctx["s"], ctx["eid"], [(2026, 10)], details=True)
    keys = [r.key for r in rep.rows]
    i = keys.index("moradia")
    assert keys[i + 1:i + 3] == ["moradia:Aluguel ou financiamento", "moradia:Luz"]
    assert rep.row("livre").total == D("-1700.00")             # transferência não entra
    assert rep.share(rep.row("moradia")) is None               # sem receitas: sem AV%


def test_fluxo_de_caixa(ctx):
    add = ctx["add"]
    add("Atrasada", "50", date(2026, 10, 10))                  # vai para hoje
    add("Salário", "3000", date(2026, 10, 20), kind="income")
    add("Aluguel", "1500", date(2026, 10, 18))
    add("Cartão", "2000", date(2026, 10, 19))
    add("Paga", "999", date(2026, 10, 16), paid=True)           # já saiu do saldo
    add("Longe", "777", date(2026, 12, 1))                      # fora do período
    f = reports.cash_flow(ctx["s"], ctx["eid"], 30, TODAY)
    assert f.start_balance == D("-899.00")                      # 100 - 999
    assert len(f.days) == 30 and f.overdue == 1
    assert f.days[0].outflow == D("50.00") and f.days[0].items == ["Atrasada"]
    assert (f.inflow, f.outflow) == (D("3000.00"), D("3550.00"))
    assert f.end_balance == D("-1449.00")
    low = f.lowest
    assert (low.day, low.balance) == (date(2026, 10, 19), D("-4449.00"))
