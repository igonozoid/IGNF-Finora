from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, categories, contacts, cost_centers, entity_admin, entries, reports
from finora.services.entries import EntryData


@pytest.fixture
def two(session, profile, plus):
    other = entity_admin.create(session, name="Padaria Sol", person_type="PJ")
    return session, profile.id, other


def test_contato_compartilhado_aparece_nas_duas_e_nao_duplica(two):
    s, a, b = two
    contacts.create(s, a, name="Contador Silva", shared=True)
    contacts.create(s, a, name="Só da A")
    names_b = [c.name for c in contacts.list_contacts(s, b)]
    assert "Contador Silva" in names_b and "Só da A" not in names_b
    with pytest.raises(ValueError, match="Já existe"):
        contacts.create(s, b, name="contador silva")              # já está visível em B
    bank_b = accounts.list_accounts(s, b)[0].id
    entries.create(s, b, EntryData(kind="expense", description="Honorários", amount=D("400"),
                                   due_date=date(2026, 10, 5), account_id=bank_b, contact="Contador Silva"))
    assert len(contacts.list_contacts(s, a)) == 2                   # não criou outro contato
    silva_b = next(c for c in contacts.list_contacts(s, b) if c.name == "Contador Silva")
    assert silva_b.shared and silva_b.entries == 1                  # conta só os lançamentos de B
    silva_a = next(c for c in contacts.list_contacts(s, a) if c.name == "Contador Silva")
    assert silva_a.entries == 0


def test_grupo_de_categorias_compartilhado_com_subcategorias(two):
    s, a, b = two
    g = categories.create(s, a, name="Veículos da família", dre_group="transporte", shared=True)
    sub = categories.create(s, a, name="Pedágio", parent_id=g)
    labels_b = [label for _cid, label in categories.choices(s, b, "expense")]
    assert "Veículos da família › Pedágio" in labels_b
    tree_b = {c.name: c for c in categories.tree(s, b)}
    assert tree_b["Veículos da família"].shared and not tree_b["Veículos da família"].own
    bank_b = accounts.list_accounts(s, b)[0].id
    entries.create(s, b, EntryData(kind="expense", description="Pedágio", amount=D("12.50"),
                                   due_date=date(2026, 10, 5), account_id=bank_b, category_id=sub))
    rep = reports.dre(s, b, [(2026, 10)])
    assert next(r for r in rep.rows if r.key == "transporte").values == [D("-12.50")]
    rep_a = reports.dre(s, a, [(2026, 10)])
    assert next(r for r in rep_a.rows if r.key == "transporte").values == [D("0")]   # cada entidade com o seu
    categories.update(s, g, name="Veículos da família", shared=False)
    assert "Veículos da família › Pedágio" not in [l for _c, l in categories.choices(s, b, "expense")]


def test_centro_de_custo_compartilhado_e_categoria_nao_compartilhada_recusada(two):
    s, a, b = two
    cc = cost_centers.create(s, a, "Obra da casa", D("1000"), shared=True)
    priv = cost_centers.create(s, a, "Só da A")
    assert [c.name for c in cost_centers.list_centers(s, b, 2026, 10)] == ["Obra da casa"]
    bank_b = accounts.list_accounts(s, b)[0].id
    entries.create(s, b, EntryData(kind="expense", description="Cimento", amount=D("300"), due_date=date(2026, 10, 5),
                                   account_id=bank_b, cost_center_id=cc))
    assert next(c for c in cost_centers.list_centers(s, b, 2026, 10)).spent == D("300")
    assert cost_centers.list_centers(s, a, 2026, 10)[0].spent == D("0")
    with pytest.raises(ValueError, match="Centro de custo inválido"):
        entries.create(s, b, EntryData(kind="expense", description="X", amount=D("1"), due_date=date(2026, 10, 5),
                                       account_id=bank_b, cost_center_id=priv))
    luz_a = dict((l, c) for c, l in categories.choices(s, a, "expense"))["Moradia › Luz"]
    with pytest.raises(ValueError, match="Categoria inválida"):
        entries.create(s, b, EntryData(kind="expense", description="Luz", amount=D("1"), due_date=date(2026, 10, 5),
                                       account_id=bank_b, category_id=luz_a))
