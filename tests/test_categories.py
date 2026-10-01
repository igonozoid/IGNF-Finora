import pytest

from finora.services import categories, dre


def _find(tree, name):
    for g in tree:
        if g.name == name:
            return g
        for c in g.children:
            if c.name == name:
                return c


def test_arvore_na_ordem_da_dre(session, profile):
    tree = categories.tree(session, profile.id)
    assert [g.dre_group for g in tree] == list(dre.GROUPS)
    assert all(c.dre_group == g.dre_group for g in tree for c in g.children)


def test_subcategoria_herda_do_grupo(session, profile):
    lazer = _find(categories.tree(session, profile.id), "Lazer")
    cid = categories.create(session, profile.id, name="Cinema", parent_id=lazer.id)
    cinema = _find(categories.tree(session, profile.id), "Cinema")
    assert cinema.id == cid and cinema.dre_group == "lazer" and cinema.kind == "expense"
    assert cinema.code == f"{lazer.code}.{len(lazer.children) + 1}"


def test_grupo_novo_precisa_de_linha_dre(session, profile):
    with pytest.raises(ValueError):
        categories.create(session, profile.id, name="Pets")
    categories.create(session, profile.id, name="Pets", dre_group="outras")
    assert _find(categories.tree(session, profile.id), "Pets").code == str(len(dre.GROUPS) + 1)


def test_receita_tem_tipo_income(session, profile):
    categories.create(session, profile.id, name="Aluguéis recebidos", dre_group="receitas")
    assert _find(categories.tree(session, profile.id), "Aluguéis recebidos").kind == "income"


def test_nome_repetido_no_mesmo_grupo(session, profile):
    lazer = _find(categories.tree(session, profile.id), "Lazer")
    with pytest.raises(ValueError):
        categories.create(session, profile.id, name="viagens", parent_id=lazer.id)


def test_nao_cria_neto(session, profile):
    viagens = _find(categories.tree(session, profile.id), "Viagens")
    with pytest.raises(ValueError):
        categories.create(session, profile.id, name="Hotel", parent_id=viagens.id)


def test_trocar_linha_dre_do_grupo_vale_para_filhos(session, profile):
    lazer = _find(categories.tree(session, profile.id), "Lazer")
    categories.update(session, lazer.id, name="Diversão", dre_group="outras")
    g = _find(categories.tree(session, profile.id), "Diversão")
    assert g.dre_group == "outras" and all(c.dre_group == "outras" for c in g.children)


def test_inativar_e_ativar(session, profile):
    lazer = _find(categories.tree(session, profile.id), "Lazer")
    categories.set_active(session, lazer.id, False)
    assert _find(categories.tree(session, profile.id), "Lazer") is None
    full = categories.tree(session, profile.id, include_inactive=True)
    assert all(not c.is_active for c in _find(full, "Lazer").children)
    categories.set_active(session, _find(full, "Viagens").id, True)  # reativa o grupo junto
    tree = categories.tree(session, profile.id)
    assert [c.name for c in _find(tree, "Lazer").children] == ["Viagens"]
