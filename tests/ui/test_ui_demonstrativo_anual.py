"""Demonstrativo anual na tela de Relatórios (Fase 3.6): Plus/Pro (D3)."""
from datetime import date


def test_demonstrativo_anual_na_tela(plus, window, sample):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "annual"))
    view = rp.views["annual"]
    assert view.year.currentData() == date.today().year
    assert view.table.columnCount() == 1 + 12 + 2                       # 12 meses + média + total
    assert view.table.horizontalHeaderItem(1).text() == "JAN" and view.table.horizontalHeaderItem(0).text() == "CATEGORIA"
    view.group_by.setCurrentIndex(view.group_by.findData("contact"))
    assert view.table.horizontalHeaderItem(0).text() == "CONTATO"
    names = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert "Empresa X" in names and "Imobiliária" in names
    assert view.export_sheet().subtitle == f"{date.today().year} · por contato"
    view.year.setCurrentIndex(view.year.findData(date.today().year - 5))
    assert view.table.rowCount() == 0


def test_demonstrativo_anual_bloqueado_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "annual")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
