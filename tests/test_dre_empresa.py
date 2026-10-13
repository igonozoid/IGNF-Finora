from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, categories, entity_admin, entries, modules, reports
from finora.services.entries import EntryData


def _cats(s, eid, kind):
    return {label.split(" › ")[-1]: cid for cid, label in categories.choices(s, eid, kind)}


def test_dre_de_empresa(session, profile, plus):
    s = session
    eid = entity_admin.create(s, name="Singolare", person_type="PJ")          # PJ: modelo empresa
    bank = accounts.list_accounts(s, eid)[0].id
    inc, exp = _cats(s, eid, "income"), _cats(s, eid, "expense")
    assert "Venda de produtos" in inc and "Simples Nacional (DAS)" in exp
    for desc, kind, cat, val in (("Venda de azeite", "income", inc["Venda de produtos"], "10000"),
                                 ("DAS", "expense", exp["Simples Nacional (DAS)"], "600"),
                                 ("Azeitonas", "expense", exp["Mercadorias e matéria-prima"], "3000"),
                                 ("Salários", "expense", exp["Salários"], "2000"),
                                 ("Aluguel", "expense", exp["Aluguel"], "1000"),
                                 ("Tarifas", "expense", exp["Tarifas bancárias"], "100"),
                                 ("Retirada", "expense", exp["Distribuição de lucros"], "1500")):
        entries.create(s, eid, EntryData(kind=kind, description=desc, amount=D(val), due_date=date(2026, 9, 10),
                                         account_id=bank, category_id=cat))
    rep = reports.dre(s, eid, [(2026, 9)])
    v = {r.key: r.total for r in rep.rows}
    assert v["liquida"] == D("9400.00") and v["bruto"] == D("6400.00") and v["operacional"] == D("3400.00")
    assert v["liquido"] == D("3300.00") and v["saldo"] == D("1800.00")
    assert rep.share(rep.row("custos")) == D("30.0")                      # % sobre a receita bruta


def test_trocar_modelo_adapta_categorias(session, profile, plus):
    s = session
    groups = {c.name: c.dre_group for c in categories.tree(s, profile.id)}
    assert groups["Moradia"] == "moradia"
    entity_admin.update(s, profile.id, name=profile.name, person_type="PF", document=None, dre_model="business")
    groups = {c.name: c.dre_group for c in categories.tree(s, profile.id)}
    assert groups["Moradia"] == "administrativas" and groups["Receitas"] == "receita_bruta"
    assert groups["Investimentos/Reserva"] == "imobilizado"
    assert [r.key for r in reports.dre(s, profile.id, [(2026, 9)]).rows][0] == "receita_bruta"
    with pytest.raises(ValueError):
        categories.create(s, profile.id, name="Lazer 2", dre_group="lazer")      # linha do outro modelo
    entity_admin.update(s, profile.id, name=profile.name, person_type="PF", document=None, dre_model="personal")
    assert {c.name: c.dre_group for c in categories.tree(s, profile.id)}["Receitas"] == "receitas"


def test_modulos_com_dependencias(session, profile):
    s, eid = session, profile.id
    assert modules.enabled(s, eid) == set()
    assert modules.set_enabled(s, eid, "livestock", True) == {"livestock", "rural", "stock"}
    assert modules.set_enabled(s, eid, "stock", False) == set()           # desliga quem depende
    modules.set_enabled(s, eid, "sales", True)
    assert modules.is_on(s, eid, "stock") and not modules.is_on(s, eid, "rural")
    with pytest.raises(ValueError):
        modules.set_enabled(s, eid, "nada", True)
