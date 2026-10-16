from finora.core import db
from finora.services import cost_centers
from tests.ui.conftest import pump


def test_cadastrar_centro_usar_no_lancamento_e_ver_consumo(plus, window, qtbot):
    window.go_to("cost_centers")
    page = window.page("cost_centers")
    assert page.empty.isVisible()
    page.name_edit.setText("Casa")
    page.budget_edit.setText("2.000,00")
    page.save_btn.click()
    pump(qtbot)
    assert page.table.rowCount() == 1 and page.table.item(0, 1).text() == "R$ 2.000,00"

    # no lançamento, o campo aparece (há centro cadastrado) e é salvo
    window.go_to("entries")
    entries_page = window.page("entries")
    mercado = next(e for e in entries_page.model.rows if e.description == "Mercado")
    entries_page.open_by_id(mercado.id)
    form = entries_page.form
    assert not form.cc_box.itemAt(0).widget().isHidden()
    form.cost_center.setCurrentIndex(form.cost_center.findText("Casa"))
    form._save()
    pump(qtbot)

    window.go_to("cost_centers")
    assert page.table.item(0, 2).text() == "− R$ 640,10" and page.table.item(0, 4).text() == "32%"
    # editar e inativar
    page.table.cellClicked.emit(0, 0)
    assert page.form_title.text() == "Editar centro de custo" and page.active.isVisible()
    page.active.setChecked(False)
    page.save_btn.click()
    pump(qtbot)
    assert page.table.rowCount() == 0
    page.show_inactive.setChecked(True)
    assert "(inativo)" in page.table.item(0, 0).text()
    # o relatório por centro de custo está liberado na Plus
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "cost_center"))
    view = rp.views["cost_center"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    assert view.table.item(0, 0).text() == "Casa"


def test_centros_bloqueados_na_free(window):
    window.go_to("cost_centers")
    assert window.page("cost_centers").locked
    with db.Session() as s:
        cost_centers.create(s, window.profile.id, "Casa")
    form = window.page("entries").form
    form._load_cost_centers()
    assert form.cost_center.count() == 1                     # só "Nenhum": o campo fica escondido na Free


def test_centro_de_lucro_so_aparece_na_receita(plus, window, qtbot):
    page = window.page("cost_centers")
    window.go_to("cost_centers")
    assert page.for_expense.isChecked() and page.for_income.isChecked()          # novo: vale para os dois
    page.name_edit.setText("Vendas")
    page.for_expense.setChecked(False)
    assert page.budget_edit.isHidden() and not page.projection_edit.isHidden()
    page.projection_edit.setText("20.000,00")
    page.save_btn.click()
    pump(qtbot)
    row = next(r for r in range(page.table.rowCount()) if page.table.item(r, 0).text() == "Vendas")
    assert page.table.item(row, 1).text() == "—" and "Projeção do mês: R$ 20.000,00" in \
        (page.table.item(row, 5).toolTip())
    window.go_to("entries")
    form = window.page("entries").form
    window.new_entry()
    assert form.cost_center.findText("Vendas") < 0                                 # despesa: não aparece
    form.kind_group.button(1).click()                                              # receita
    assert form.cost_center.findText("Vendas") >= 0
    form.cancel_btn.click()
