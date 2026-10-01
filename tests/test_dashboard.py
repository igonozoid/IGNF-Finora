from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, categories, dashboard, entries
from finora.services.entries import EntryData

TODAY = date(2026, 10, 15)


@pytest.fixture
def ctx(session, profile):
    exp = {label: cid for cid, label in categories.choices(session, profile.id, "expense")}
    inc = {label: cid for cid, label in categories.choices(session, profile.id, "income")}
    bank = accounts.list_accounts(session, profile.id)[0].id

    def add(desc, amount, due, cat=None, kind="expense", paid=False, **kw):
        cid = (inc if kind == "income" else exp).get(cat) if cat else None
        return entries.create(session, profile.id, EntryData(
            kind=kind, description=desc, amount=D(amount), due_date=due, account_id=bank,
            category_id=cid, paid=paid, **kw))[0]

    return dict(s=session, eid=profile.id, bank=bank, add=add)


def test_kpis(ctx):
    add = ctx["add"]
    add("Salário", "5000", date(2026, 10, 5), "Receitas › Salário", kind="income", paid=True)
    add("Freela", "800", date(2026, 11, 2), "Receitas › Renda extra", kind="income")       # dentro de 30 dias
    add("Bônus", "999", date(2026, 12, 20), "Receitas › Renda extra", kind="income")       # fora de 30 dias
    add("Aluguel", "1500", date(2026, 10, 10), "Moradia › Aluguel ou financiamento")      # atrasado
    add("Mercado", "600", date(2026, 10, 20), "Alimentação › Supermercado")
    add("Reserva", "1000", date(2026, 10, 25), "Investimentos/Reserva › Reserva de emergência")
    add("Luz setembro", "200", date(2026, 9, 10), "Moradia › Luz", paid=True)
    k = dashboard.kpis(ctx["s"], ctx["eid"], TODAY)
    assert k.balance == D("100") + D("5000") - D("200") and k.accounts == 1
    assert (k.receivable, k.receivable_n) == (D("800.00"), 1)
    assert (k.payable, k.payable_n) == (D("3100.00"), 3) and k.late_n == 1
    assert k.result == D("2900.00")        # 5000 - 1500 - 600 (reserva não entra)
    assert k.prev_result == D("-200.00")


def test_monthly_flow(ctx):
    add = ctx["add"]
    add("Salário", "5000", date(2026, 10, 5), kind="income")
    add("Mercado", "600", date(2026, 10, 20))
    add("Antigo", "300", date(2026, 5, 1))
    add("Fora da janela", "999", date(2026, 4, 30))
    entries.create(ctx["s"], ctx["eid"], EntryData(kind="transfer", description="t", amount=D(50),
                                                   due_date=date(2026, 10, 1), account_id=ctx["bank"],
                                                   dest_account_id=accounts.create(ctx["s"], ctx["eid"], name="C",
                                                                                   kind="cash", opening_balance=D(0))))
    flow = dashboard.monthly_flow(ctx["s"], ctx["eid"], 6, TODAY)
    assert [(f.year, f.month) for f in flow] == [(2026, m) for m in range(5, 11)]
    assert (flow[0].income, flow[0].expense) == (D("0.00"), D("300.00"))
    assert (flow[-1].income, flow[-1].expense) == (D("5000.00"), D("600.00"))  # transferência não conta


def test_due_soon(ctx):
    add = ctx["add"]
    add("Atrasada", "10", date(2026, 10, 1))
    add("Amanhã", "20", date(2026, 10, 16))
    add("Daqui 7", "30", date(2026, 10, 22))
    add("Daqui 8", "40", date(2026, 10, 23))
    add("Paga", "50", date(2026, 10, 16), paid=True)
    assert [e.description for e in dashboard.due_soon(ctx["s"], ctx["eid"], 7, TODAY)] == ["Atrasada", "Amanhã", "Daqui 7"]


def test_top_expenses_por_grupo(ctx):
    add = ctx["add"]
    add("Aluguel", "1500", date(2026, 10, 10), "Moradia › Aluguel ou financiamento")
    add("Luz", "200", date(2026, 10, 10), "Moradia › Luz")
    add("Mercado", "600", date(2026, 10, 20), "Alimentação › Supermercado")
    add("Sem cat", "50", date(2026, 10, 20))
    add("Reserva", "5000", date(2026, 10, 25), "Investimentos/Reserva › Reserva de emergência")
    add("Outro mês", "9999", date(2026, 11, 1), "Alimentação › Supermercado")
    assert dashboard.top_expenses(ctx["s"], ctx["eid"], 2026, 10) == [
        ("Moradia", D("1700.00")), ("Alimentação", D("600.00")), ("Sem categoria", D("50.00"))]
