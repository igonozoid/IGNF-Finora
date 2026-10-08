from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from finora.services import accounts, cards, categories, entries, reports
from finora.services.entries import EntryData

TODAY = date(2026, 10, 15)


@pytest.fixture
def ctx(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id                       # Banco, saldo inicial 100
    cash = accounts.create(s, eid, name="Carteira", kind="cash", opening_balance=D("20"))
    exp = {l: c for c, l in categories.choices(s, eid, "expense")}
    inc = {l: c for c, l in categories.choices(s, eid, "income")}

    def add(desc, amount, due, kind="expense", cat=None, paid=False, paid_date=None, acc=None, **kw):
        cid = (inc if kind == "income" else exp).get(cat) if cat else None
        return entries.create(s, eid, EntryData(kind=kind, description=desc, amount=D(amount), due_date=due,
                                                account_id=acc or bank, category_id=cid, paid=paid,
                                                paid_date=paid_date, **kw))[0]
    return dict(s=s, eid=eid, bank=bank, cash=cash, add=add)


def test_periodos_novos():
    assert reports.period_months("1m", TODAY) == [(2026, 10)]
    assert reports.period_months("last_month", date(2026, 1, 10)) == [(2025, 12)]
    assert reports.period_range("3m", TODAY) == (date(2026, 8, 1), date(2026, 10, 31))


def test_extrato_da_conta(ctx):
    add = ctx["add"]
    add("Salário", "5000", date(2026, 9, 5), kind="income", paid=True, paid_date=date(2026, 9, 5))   # antes
    add("Aluguel", "1500", date(2026, 10, 8), "expense", paid=True, paid_date=date(2026, 10, 9))
    add("Luz", "200", date(2026, 10, 9))                                                            # não pago
    add("Saque", "300", date(2026, 10, 10), kind="transfer", paid=True, paid_date=date(2026, 10, 10),
        dest_account_id=ctx["cash"])
    st = reports.account_statement(ctx["s"], ctx["bank"], date(2026, 10, 1), date(2026, 10, 31))
    assert st.opening == D("5100.00")                                   # 100 + salário de setembro
    assert [(l.day, l.description, l.outflow, l.balance) for l in st.lines] == [
        (date(2026, 10, 9), "Aluguel", D("1500"), D("3600.00")),
        (date(2026, 10, 10), "Saque", D("300"), D("3300.00"))]
    assert st.lines[1].category == "Transferência" and st.closing == D("3300.00")
    # o mesmo saque aparece como entrada no extrato da carteira
    st2 = reports.account_statement(ctx["s"], ctx["cash"], date(2026, 10, 1), date(2026, 10, 31))
    assert (st2.opening, st2.inflow, st2.closing) == (D("20.00"), D("300"), D("320.00"))
    # fechamento bate com o saldo da conta
    saldo = next(a.balance for a in accounts.list_accounts(ctx["s"], ctx["eid"]) if a.id == ctx["bank"])
    assert saldo == st.closing


def test_extrato_do_cartao_usa_a_data_da_compra(ctx):
    s, eid = ctx["s"], ctx["eid"]
    card = accounts.create(s, eid, name="Itaú", kind="card", opening_balance=D(0), closing_day=25, due_day=5)
    ctx["add"]("Mercado", "80", date(2026, 10, 12), acc=card)
    st = reports.account_statement(s, card, date(2026, 10, 1), date(2026, 10, 31))
    assert [(l.day, l.outflow) for l in st.lines] == [(date(2026, 10, 12), D("80"))]


def test_por_categoria(ctx):
    add = ctx["add"]
    add("Aluguel", "1500", date(2026, 10, 8), cat="Moradia › Aluguel ou financiamento")
    add("Luz", "200", date(2026, 10, 9), cat="Moradia › Luz")
    add("Luz 2", "50", date(2026, 10, 20), cat="Moradia › Luz")
    add("Salário", "5000", date(2026, 10, 5), kind="income", cat="Receitas › Salário")
    add("Sem cat", "30", date(2026, 10, 5))
    add("Outro mês", "999", date(2026, 11, 5), cat="Moradia › Luz")
    rows = reports.by_category(ctx["s"], ctx["eid"], date(2026, 10, 1), date(2026, 10, 31))
    assert [(r.kind, r.group, r.category, r.total, r.count) for r in rows] == [
        ("income", "Receitas", "Salário", D("5000.00"), 1),
        ("expense", "Moradia", "Aluguel ou financiamento", D("1500.00"), 1),
        ("expense", "Moradia", "Luz", D("250.00"), 2),
        ("expense", "Sem categoria", "Sem categoria", D("30.00"), 1)]


def test_por_contato(ctx):
    add = ctx["add"]
    add("Aula", "400", date(2026, 10, 5), kind="income", contact="Pedro")
    add("Reembolso", "50", date(2026, 10, 6), contact="Pedro")
    add("Luz", "200", date(2026, 10, 9), contact="Enel")
    add("Sem contato", "10", date(2026, 10, 9))
    rows = reports.by_contact(ctx["s"], ctx["eid"], date(2026, 10, 1), date(2026, 10, 31))
    assert [(r.contact, r.received, r.paid, r.count) for r in rows] == [
        ("Pedro", D("400.00"), D("50.00"), 2), ("Enel", D("0.00"), D("200.00"), 1)]


def test_inadimplencia_com_faixas_e_fatura(ctx):
    s, eid, add = ctx["s"], ctx["eid"], ctx["add"]
    add("Luz", "200", date(2026, 10, 5), contact="Enel")                 # 10 dias
    add("Água", "80", date(2026, 8, 1))                                  # 75 dias
    add("Aula não paga", "400", date(2026, 9, 1), kind="income", contact="Pedro")   # 44 dias
    add("Paga", "999", date(2026, 9, 1), paid=True)
    add("Futura", "999", date(2026, 10, 30))
    card = accounts.create(s, eid, name="Itaú", kind="card", opening_balance=D(0), closing_day=25, due_day=5)
    add("Loja", "120", date(2026, 9, 10), acc=card)                      # fatura venceu em 05/10
    rep = reports.overdue(s, eid, TODAY)
    assert [(i.description, i.days) for i in rep.payables] == [
        ("Água", 75), ("Luz", 10), ("Fatura Itaú out/2026", 10)]
    assert rep.payables[2].entry_id is None and rep.payables[2].card_account_id == card
    assert [(i.description, i.contact, i.days) for i in rep.receivables] == [("Aula não paga", "Pedro", 44)]
    assert rep.buckets(rep.payables) == [("Até 30 dias", D("320.00"), 2), ("31 a 60 dias", D("0.00"), 0),
                                         ("61 a 90 dias", D("80.00"), 1), ("Mais de 90 dias", D("0.00"), 0)]


def test_analitico_lista_receitas_e_despesas_do_periodo(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    for kind, desc, day in (("expense", "Luz", 5), ("income", "Salário", 1), ("expense", "Fora", 40)):
        when = date(2026, 10, 1) + timedelta(days=day - 1)
        entries.create(s, eid, EntryData(kind=kind, description=desc, amount=D("10"), due_date=when,
                                         account_id=bank))
    out = reports.analytical(s, eid, date(2026, 10, 1), date(2026, 10, 31))
    assert [e.description for e in out] == ["Salário", "Luz"]
    assert [e.description for e in reports.analytical(s, eid, date(2026, 10, 1), date(2026, 10, 31), "expense")] \
        == ["Luz"]


def test_agenda_comparativo_patrimonio_e_caixa(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    exp = {label.split(" › ")[-1]: cid for cid, label in categories.choices(s, eid, "expense")}
    for m, val, paid in ((8, "100", True), (9, "150", True), (10, "200", False)):
        entries.create(s, eid, EntryData(kind="expense", description="Luz", amount=D(val), due_date=date(2026, m, 15),
                                         account_id=bank, category_id=exp["Luz"], paid=paid,
                                         paid_date=date(2026, m, 15) if paid else None))
    entries.create(s, eid, EntryData(kind="income", description="Salário", amount=D("1000"),
                                     due_date=date(2026, 9, 5), account_id=bank, paid=True, paid_date=date(2026, 9, 5)))
    # agenda: só o que está em aberto no período
    ag = reports.agenda(s, eid, date(2026, 10, 1), date(2026, 10, 31))
    assert [e.description for e in ag] == ["Luz"]
    assert reports.agenda_range("next_month", date(2026, 10, 7)) == (date(2026, 11, 1), date(2026, 11, 30))
    # comparativo: a Luz mês a mês, média e total
    months = [(2026, 8), (2026, 9), (2026, 10)]
    luz = next(r for r in reports.category_by_month(s, eid, months) if r.category == "Luz")
    assert luz.values == [D("100.00"), D("150.00"), D("200.00")] and luz.average == D("150.00")
    # patrimônio: saldo no fim de cada mês (o banco começa com 100)
    bal = next(r for r in reports.balance_history(s, eid, months) if r.account == "Banco")
    assert bal.values == [D("0.00"), D("850.00"), D("850.00")]
    # caixa: só o realizado
    cash = reports.cash_history(s, eid, months)
    assert [(c.inflow, c.outflow) for c in cash] == [(D("0.00"), D("100.00")), (D("1000.00"), D("150.00")),
                                                     (D("0.00"), D("0.00"))]
