"""Filtro "Só a revisar" em Categorias e Centros de custo (Fase 4.6)."""
from finora.core import db
from finora.services import categories, cost_centers


def test_categorias_a_revisar(window):
    eid = window.profile.id
    with db.Session() as s:
        group = categories.tree(s, eid)[-1]
        cid = categories.create(s, eid, name="Criada no lançamento", parent_id=group.id, needs_review=True)
    window.go_to("categories")
    page = window.page("categories")
    page.refresh()
    assert not page.only_review.isHidden() and page.only_review.text() == "Só a revisar (1)"
    page.only_review.setChecked(True)
    assert page.tree.topLevelItemCount() == 1
    child = page.tree.topLevelItem(0).child(0)
    assert "a revisar" in child.text(0)
    page.refresh(select_id=cid)
    page.name_edit.setText("Conferida")
    page._save()
    assert page.only_review.text() == "Só a revisar (0)"


def test_centros_a_revisar(plus, window):
    with db.Session() as s:
        cost_centers.create(s, window.profile.id, "Obra do MCC", needs_review=True)
    window.go_to("cost_centers")
    page = window.page("cost_centers")
    page.refresh()
    assert not page.only_review.isHidden()
    page.only_review.setChecked(True)
    assert [c.name for c in page.items] == ["Obra do MCC"]
    assert "a revisar" in page.table.item(0, 0).text()
