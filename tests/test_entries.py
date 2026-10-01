from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, categories, contacts, entries
from finora.services.entries import EntryData

TODAY = date(2026, 10, 15)


@pytest.fixture
def ctx(session, profile):
    bank = accounts.list_accounts(session, profile.id)[0].id
    cash = accounts.create(session, profile.id, name="Carteira", kind="cash", opening_balance=D(0))
    cats = dict((label, cid) for cid, label in categories.choices(session, profile.id, "expense"))
    incs = dict((label, cid) for cid, label in categories.choices(session, profile.id, "income"))
    return dict(s=session, eid=profile.id, bank=bank, cash=cash,
                luz=cats["Moradia › Luz"], mercado=cats["Alimentação › Supermercado"], salario=incs["Receitas › Salário"])


def _data(c, **kw):
    base = dict(kind="expense", description="Conta de luz", amount=D("120.50"), due_date=date(2026, 10, 10),
                account_id=c["bank"], category_id=c["luz"])
    base.update(kw)
    return EntryData(**base)


def _list(c, filter="all", year=2026, month=10, search=""):
    return entries.list_entries(c["s"], c["eid"], year=year, month=month, filter=filter, search=search, today=TODAY)


# ---------- utilitários ----------
def test_add_months_respeita_fim_do_mes():
    assert entries.occurrence(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)
    assert entries.occurrence(date(2026, 1, 31), "monthly", 2) == date(2026, 3, 31)
    assert entries.occurrence(date(2026, 12, 15), "monthly", 1) == date(2027, 1, 15)
    assert entries.occurrence(date(2026, 10, 1), "weekly", 2) == date(2026, 10, 15)
    assert entries.occurrence(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)


def test_split_parcelas():
    assert entries.split(D("100.00"), 3) == [D("33.34"), D("33.33"), D("33.33")]
    assert sum(entries.split(D("1000.01"), 7)) == D("1000.01")


# ---------- criação ----------
def test_cria_simples_e_status(ctx):
    entries.create(ctx["s"], ctx["eid"], _data(ctx))
    e = _list(ctx)[0]
    assert e.category == "Luz" and e.account == "Banco" and not e.is_paid
    assert e.status_label(TODAY) == "Atrasado"  # venceu dia 10, hoje é 15
    assert e.status_label(date(2026, 10, 1)) == "A pagar"


def test_validacoes(ctx):
    with pytest.raises(ValueError):
        entries.create(ctx["s"], ctx["eid"], _data(ctx, amount=D(0)))
    with pytest.raises(ValueError):
        entries.create(ctx["s"], ctx["eid"], _data(ctx, description=" "))
    with pytest.raises(ValueError):  # categoria de despesa numa receita
        entries.create(ctx["s"], ctx["eid"], _data(ctx, kind="income"))
    with pytest.raises(ValueError):
        entries.create(ctx["s"], ctx["eid"], _data(ctx, kind="transfer", dest_account_id=ctx["bank"]))
    accounts.set_active(ctx["s"], ctx["cash"], False)
    with pytest.raises(ValueError):  # conta inativa
        entries.create(ctx["s"], ctx["eid"], _data(ctx, account_id=ctx["cash"]))
    assert _list(ctx) == []


def test_parcelado(ctx):
    ids = entries.create(ctx["s"], ctx["eid"], _data(ctx, description="Geladeira", amount=D("1000.00"),
                                                     repeat="installments", times=3, paid=True))
    assert len(ids) == 3
    out = [entries.get(ctx["s"], i) for i in ids]
    assert [e.installment for e in out] == ["1/3", "2/3", "3/3"]
    assert [e.amount for e in out] == [D("333.34"), D("333.33"), D("333.33")]
    assert [e.due_date for e in out] == [date(2026, 10, 10), date(2026, 11, 10), date(2026, 12, 10)]
    assert [e.is_paid for e in out] == [True, False, False]  # só a 1ª nasce paga
    assert len({e.series_id for e in out}) == 1 and not out[0].is_recurring


def test_recorrente(ctx):
    ids = entries.create(ctx["s"], ctx["eid"], _data(ctx, repeat="monthly", times=12))
    out = [entries.get(ctx["s"], i) for i in ids]
    assert all(e.amount == D("120.50") and e.is_recurring and e.installment is None for e in out)
    assert out[-1].due_date == date(2027, 9, 10)


def test_transferencia_move_saldo(ctx):
    entries.create(ctx["s"], ctx["eid"], _data(ctx, kind="transfer", description="Saque", amount=D("40"),
                                               category_id=ctx["luz"], contact="Ignorado",
                                               dest_account_id=ctx["cash"], paid=True))
    e = _list(ctx)[0]
    assert e.category is None and e.contact is None and e.dest_account == "Carteira"
    saldos = {a.id: a.balance for a in accounts.list_accounts(ctx["s"], ctx["eid"])}
    assert saldos[ctx["bank"]] == D("60.00") and saldos[ctx["cash"]] == D("40.00")


def test_contato_criado_pelo_nome(ctx):
    entries.create(ctx["s"], ctx["eid"], _data(ctx, contact="Enel"))
    entries.create(ctx["s"], ctx["eid"], _data(ctx, contact=" enel "))
    assert contacts.names(ctx["s"], ctx["eid"]) == ["Enel"]


# ---------- filtros e totais ----------
def test_filtros(ctx):
    s, eid = ctx["s"], ctx["eid"]
    entries.create(s, eid, _data(ctx))                                                     # atrasada
    entries.create(s, eid, _data(ctx, description="Mercado", category_id=ctx["mercado"], due_date=date(2026, 10, 20)))
    entries.create(s, eid, _data(ctx, kind="income", description="Salário", amount=D("5000"),
                                 category_id=ctx["salario"], due_date=date(2026, 10, 5), paid=True,
                                 paid_date=date(2026, 10, 5)))
    entries.create(s, eid, _data(ctx, description="Luz setembro", due_date=date(2026, 9, 10)))  # atrasada, outro mês
    names = lambda f, **kw: [e.description for e in _list(ctx, f, **kw)]
    assert names("all") == ["Salário", "Conta de luz", "Mercado"]
    assert names("payable") == ["Conta de luz", "Mercado"]
    assert names("receivable") == []
    assert names("late") == ["Luz setembro", "Conta de luz"]  # atrasados de qualquer mês
    assert names("paid") == ["Salário"]
    assert names("all", search="merc") == ["Mercado"]
    t = entries.month_totals(s, eid, 2026, 10)
    assert t.payable == D("241.00") and t.receivable == D("0.00") and t.balance == D("-241.00")


# ---------- edição e exclusão ----------
def test_editar_este_e_proximos(ctx):
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, repeat="monthly", times=4))
    entries.set_paid(s, ids[2], True, date(2026, 12, 10))
    n = entries.update(s, ids[1], _data(ctx, description="Luz (nova tarifa)", amount=D("150"),
                                        due_date=date(2026, 11, 12)), scope="following")
    assert n == 2  # o 2º e o 4º; o 3º já está pago
    out = [entries.get(s, i) for i in ids]
    assert [e.amount for e in out] == [D("120.50"), D("150"), D("120.50"), D("150")]
    assert out[1].due_date == date(2026, 11, 12) and out[3].due_date == date(2027, 1, 10)


def test_editar_so_este(ctx):
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, repeat="monthly", times=3))
    assert entries.in_series(s, ids[0]) == 2
    entries.update(s, ids[0], _data(ctx, amount=D("99")))
    assert [entries.get(s, i).amount for i in ids] == [D("99"), D("120.50"), D("120.50")]


def test_excluir_este_e_proximos(ctx):
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, repeat="monthly", times=4))
    assert entries.delete(s, ids[1], scope="following") == 3
    assert [e.id for e in _list(ctx)] == [ids[0]]


def test_marcar_pago(ctx):
    s = ctx["s"]
    (i,) = entries.create(s, ctx["eid"], _data(ctx))
    entries.set_paid(s, i, True, date(2026, 10, 11))
    e = entries.get(s, i)
    assert e.is_paid and e.paid_date == date(2026, 10, 11) and e.status_label(TODAY) == "Pago"
    assert accounts.list_accounts(s, ctx["eid"])[0].balance == D("-20.50")
    entries.set_paid(s, i, False)
    assert not entries.get(s, i).is_paid
