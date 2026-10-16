from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, cost_centers, entries, reports
from finora.services.entries import EntryData


def _entry(s, eid, bank, cc, amount, when, kind="expense", desc="Gasto"):
    return entries.create(s, eid, EntryData(kind=kind, description=desc, amount=D(amount), due_date=when,
                                            account_id=bank, cost_center_id=cc))[0]


def test_cadastro_e_validacoes(session, profile):
    s, eid = session, profile.id
    casa = cost_centers.create(s, eid, "Casa", D("1000"))
    cost_centers.create(s, eid, "carro")
    with pytest.raises(ValueError, match="Já existe"):
        cost_centers.create(s, eid, "CASA")
    with pytest.raises(ValueError, match="nome"):
        cost_centers.create(s, eid, " ")
    with pytest.raises(ValueError, match="negativo"):
        cost_centers.update(s, casa, "Casa", D("-1"))
    assert [n for _i, n in cost_centers.choices(s, eid)] == ["carro", "Casa"]
    cost_centers.update(s, casa, "Casa", D("1000"), is_active=False)
    assert [n for _i, n in cost_centers.choices(s, eid)] == ["carro"]
    assert [n for _i, n in cost_centers.choices(s, eid, keep_id=casa)] == ["carro", "Casa"]   # já escolhido


def test_orcado_x_realizado_do_mes(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    casa = cost_centers.create(s, eid, "Casa", D("1000"))
    carro = cost_centers.create(s, eid, "Carro", D("300"))
    viagem = cost_centers.create(s, eid, "Viagem")
    _entry(s, eid, bank, casa, "850", date(2026, 10, 5))
    _entry(s, eid, bank, carro, "350", date(2026, 10, 9))
    _entry(s, eid, bank, carro, "100", date(2026, 9, 9))                       # outro mês
    _entry(s, eid, bank, viagem, "200", date(2026, 10, 1), kind="income", desc="Reembolso")
    by = {c.name: c for c in cost_centers.list_centers(s, eid, 2026, 10)}
    assert (by["Casa"].spent, by["Casa"].status) == (D("850"), "warn")        # 85%
    assert (by["Carro"].spent, by["Carro"].status, by["Carro"].count) == (D("350"), "over", 1)
    assert (by["Viagem"].received, by["Viagem"].status) == (D("200"), "none")
    with pytest.raises(ValueError, match="inative"):
        cost_centers.delete(s, casa)
    vazio = cost_centers.create(s, eid, "Vazio")
    cost_centers.delete(s, vazio)


def test_lancamento_guarda_o_centro_e_relatorio(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    casa = cost_centers.create(s, eid, "Casa", D("1000"))
    eid1 = _entry(s, eid, bank, casa, "400", date(2026, 10, 5))
    _entry(s, eid, bank, None, "50", date(2026, 10, 6))
    assert entries.get(s, eid1).cost_center == "Casa"
    rep = reports.by_cost_center(s, eid, date(2026, 9, 1), date(2026, 10, 31))
    assert [(r.name, r.budget, r.spent) for r in rep] == [("Casa", D("2000.00"), D("400.00")),
                                                          ("Sem centro de custo", None, D("50.00"))]
    # transferência não leva centro de custo
    other = accounts.create(s, eid, name="Carteira", kind="cash", opening_balance=D("0"))
    (t_id,) = entries.create(s, eid, EntryData(kind="transfer", description="Saque", amount=D("10"),
                                               due_date=date(2026, 10, 7), account_id=bank, dest_account_id=other,
                                               cost_center_id=casa))
    assert entries.get(s, t_id).cost_center_id is None


# ---------- aplica a despesas/receitas e projeção (MCC: centro de custo / centro de lucro) ----------
def test_centro_so_de_receita_com_projecao(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    vendas = cost_centers.create(s, eid, "Vendas", applies_expense=False, applies_income=True,
                                 projection=D("20000"), budget=D("999"))
    adm = cost_centers.create(s, eid, "Administrativo", D("3000"), applies_income=False)
    lavoura = cost_centers.create(s, eid, "Lavoura", D("8000"), projection=D("15000"))     # os dois
    names = lambda kind: [n for _i, n in cost_centers.choices(s, eid, kind=kind)]
    assert names("expense") == ["Administrativo", "Lavoura"]
    assert names("income") == ["Lavoura", "Vendas"]
    assert names(None) == ["Administrativo", "Lavoura", "Vendas"]                         # regras: todos
    with pytest.raises(ValueError, match="não vale para despesas"):
        _entry(s, eid, bank, vendas, "10", date(2026, 10, 5))
    with pytest.raises(ValueError, match="não vale para receitas"):
        _entry(s, eid, bank, adm, "10", date(2026, 10, 5), kind="income")
    _entry(s, eid, bank, vendas, "5000", date(2026, 10, 5), kind="income", desc="Venda")
    by = {c.name: c for c in cost_centers.list_centers(s, eid, 2026, 10)}
    v = by["Vendas"]
    assert (v.applies_expense, v.applies_income, v.budget, v.projection) == (False, True, None, D("20000"))
    assert v.received == D("5000") and v.income_share == D("0.25") and v.applies_label == "Só receitas"
    assert by["Administrativo"].projection is None and by["Lavoura"].applies_label == "Despesas e receitas"
    with pytest.raises(ValueError, match="Marque se o centro vale"):
        cost_centers.create(s, eid, "Nada", applies_expense=False, applies_income=False)
    with pytest.raises(ValueError, match="projeção não pode ser negativa"):
        cost_centers.update(s, lavoura, "Lavoura", D("8000"), projection=D("-1"))
    cost_centers.update(s, lavoura, "Lavoura", D("8000"))                                  # omitidos: mantém
    assert next(c for c in cost_centers.list_centers(s, eid, 2026, 10) if c.name == "Lavoura").projection == D("15000")
    cost_centers.update(s, lavoura, "Lavoura", D("8000"), applies_income=False)          # deixa de valer: zera
    assert next(c for c in cost_centers.list_centers(s, eid, 2026, 10) if c.name == "Lavoura").projection is None
