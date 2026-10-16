"""Reclassificar categorias na DRE em lote (Fase 2.14)."""
import shutil
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import select

from finora.models import AuditLog, Budget, Category, Entry, ImportMap
from finora.services import accounts, categories, entries, period_lock, reclassify, rules
from finora.services.entries import EntryData
from finora.services.mcc_import import mapper, reader

DATA = Path(__file__).parent / "data"


def _cat(s, eid, name, parent=None):
    q = select(Category).where(Category.entity_id == eid, Category.name == name)
    if parent:
        q = q.where(Category.parent_id == parent)
    return s.scalar(q)


def test_itens_do_mcc_vao_para_a_linha_certa(session, plus, tmp_path):
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    with reader.open_copy(p) as con:
        r = mapper.import_companies(session, con)
    s, agro = session, r.entities[1]
    mcc = _cat(s, agro, "Despesas do MCC")
    sug = {x.name: x for x in reclassify.suggest(s, agro, mcc.id)}
    assert (sug["Adubos e fertilizantes"].target, sug["Salários"].target, sug["Tarifas bancárias"].target) == \
        ("custos", "pessoal", "despesas_fin")                           # linhas sem grupo ainda
    assert "adubo" in sug["Adubos e fertilizantes"].reason
    assert sug["Energia elétrica"].target is None                       # já está em Despesas administrativas
    assert sug["Energia elétrica"].entries == 3

    energia = sug["Energia elétrica"].category_id                       # tem lançamento em fevereiro (fechado)
    with pytest.raises(ValueError, match="período fechado"):
        reclassify.reclassify(s, agro, {sug["Salários"].category_id: "pessoal", energia: "custos"})
    assert _cat(s, agro, "Despesas com pessoal") is None                # nada mudou, nem grupo novo

    out = reclassify.reclassify(s, agro, {x.category_id: x.target for x in sug.values() if x.target})
    assert (out.moved, out.merged) == (3, 0)
    adubo = s.get(Category, sug["Adubos e fertilizantes"].category_id)
    grupo = s.get(Category, adubo.parent_id)
    assert (grupo.name, grupo.dre_group, adubo.dre_group) == ("Custos dos produtos e serviços", "custos", "custos")
    assert s.get(Category, sug["Tarifas bancárias"].category_id).dre_group == "despesas_fin"
    assert any("Reclassificou" in x for x in s.scalars(select(AuditLog.summary)))

    period_lock.set_lock(s, agro, None)                                 # reaberto, a energia pode ir
    reclassify.reclassify(s, agro, {energia: grupo.id})
    assert s.get(Category, energia).parent_id == grupo.id


def test_regra_nome_igual_e_juntar(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    mcc = categories.create(s, eid, name="Despesas do MCC", dre_group="outras")
    mercado = categories.create(s, eid, name="Supermercado", parent_id=mcc)
    uber = categories.create(s, eid, name="Uber e táxi", parent_id=mcc)
    clube = categories.create(s, eid, name="Mensalidade do clube", parent_id=mcc)
    roupas = categories.create(s, eid, name="Roupas e calçados", parent_id=mcc)
    lazer = _cat(s, eid, "Lazer")
    rules.create(s, eid, text="clube", category_id=_cat(s, eid, "Hobbies", lazer.id).id)
    alim = _cat(s, eid, "Alimentação")
    twin = _cat(s, eid, "Supermercado", alim.id)
    e = entries.create(s, eid, EntryData(kind="expense", description="Compras", amount=D("300"),
                                         due_date=date(2026, 10, 5), account_id=bank, category_id=mercado))
    s.add_all([Budget(entity_id=eid, category_id=mercado, amount=D("200")),
               Budget(entity_id=eid, category_id=twin.id, amount=D("800")),
               ImportMap(source="mcc", kind="itens", source_id="1|D|supermercado", target=str(mercado))])
    s.commit()

    sug = {x.name: x for x in reclassify.suggest(s, eid, mcc)}
    assert sug["Supermercado"].target == alim.id and "já existe" in sug["Supermercado"].reason
    assert sug["Uber e táxi"].target == _cat(s, eid, "Transporte").id
    assert sug["Mensalidade do clube"].target == lazer.id and "regra" in sug["Mensalidade do clube"].reason
    assert sug["Roupas e calçados"].target is None                     # "roupa" é de Outras: já está lá

    with pytest.raises(ValueError, match="outro tipo"):
        reclassify.reclassify(s, eid, {uber: _cat(s, eid, "Receitas").id})
    out = reclassify.reclassify(s, eid, {mercado: alim.id, uber: "transporte", clube: lazer.id})
    assert (out.moved, out.merged, out.entries) == (2, 1, 1)
    assert s.get(Category, mercado) is None and s.get(Entry, e).category_id == twin.id
    assert s.scalar(select(Budget.amount).where(Budget.category_id == twin.id)) == D("1000.00")
    assert s.scalar(select(ImportMap.target)) == str(twin.id)
    assert s.get(Category, uber).parent_id == _cat(s, eid, "Transporte").id   # a linha já tinha grupo: usa ele
    assert s.get(Category, uber).code.startswith(_cat(s, eid, "Transporte").code + ".")
