from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, budgets, categories, entries
from finora.services.entries import EntryData

OCT = (date(2026, 10, 1), date(2026, 10, 31))


def _ids(s, eid):
    exp = {label: cid for cid, label in categories.choices(s, eid, "expense")}
    groups = {g.name: g.id for g in categories.tree(s, eid)}
    return exp, groups


def _spend(s, eid, cat, amount, when=date(2026, 10, 5)):
    bank = accounts.list_accounts(s, eid)[0].id
    entries.create(s, eid, EntryData(kind="expense", description="Gasto", amount=D(amount), due_date=when,
                                     account_id=bank, category_id=cat))


def test_orcamento_por_subcategoria_e_soma_no_grupo(session, profile):
    s, eid = session, profile.id
    exp, groups = _ids(s, eid)
    mercado = exp["Alimentação › Supermercado"]
    budgets.set_budget(s, eid, mercado, D("800"))
    _spend(s, eid, mercado, "700")
    _spend(s, eid, mercado, "50", date(2026, 9, 30))                     # outro mês
    rows = {r.name: r for r in budgets.report(s, eid, *OCT)}
    assert (rows["Supermercado"].planned, rows["Supermercado"].actual, rows["Supermercado"].status) == \
        (D("800"), D("700"), "warn")
    assert rows["Alimentação"].own is None and rows["Alimentação"].monthly == D("800")      # soma das filhas
    # orçamento próprio no grupo vale mais que a soma
    budgets.set_budget(s, eid, groups["Alimentação"], D("1000"))
    rows = {r.name: r for r in budgets.report(s, eid, *OCT)}
    assert rows["Alimentação"].planned == D("1000") and rows["Alimentação"].left == D("300")
    # período de 2 meses: orçamento x 2
    two = {r.name: r for r in budgets.report(s, eid, date(2026, 9, 1), date(2026, 10, 31))}
    assert two["Supermercado"].planned == D("1600") and two["Supermercado"].actual == D("750")


def test_apagar_validacoes_e_so_usados(session, profile):
    s, eid = session, profile.id
    exp, _groups = _ids(s, eid)
    luz = exp["Moradia › Luz"]
    budgets.set_budget(s, eid, luz, D("200"))
    budgets.set_budget(s, eid, luz, D("250"))                            # atualiza
    assert next(r for r in budgets.report(s, eid, *OCT) if r.category_id == luz).own == D("250")
    budgets.set_budget(s, eid, luz, None)                                # apaga
    assert budgets.report(s, eid, *OCT, only_used=True) == []
    salario = dict((label, cid) for cid, label in categories.choices(s, eid, "income"))["Receitas › Salário"]
    with pytest.raises(ValueError, match="despesa"):
        budgets.set_budget(s, eid, salario, D("10"))
    with pytest.raises(ValueError, match="negativo"):
        budgets.set_budget(s, eid, luz, D("-1"))


def test_aviso_de_estouro(session, profile):
    s, eid = session, profile.id
    exp, _groups = _ids(s, eid)
    luz = exp["Moradia › Luz"]
    budgets.set_budget(s, eid, luz, D("150"))
    _spend(s, eid, luz, "100")
    assert budgets.overspent(s, eid, luz, date(2026, 10, 5)) is None
    _spend(s, eid, luz, "80.40")
    msg = budgets.overspent(s, eid, luz, date(2026, 10, 5))
    assert "Luz passou do orçamento de outubro" in msg and "R$ 180,40 de R$ 150,00" in msg
