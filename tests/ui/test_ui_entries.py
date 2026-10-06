from datetime import date
from decimal import Decimal as D

from PySide6.QtCore import QDate

from finora.core import db
from finora.services import accounts


def _page(window):
    window.go_to("entries")
    return window.page("entries")


def _fill(form, kind="expense", desc="Internet", amount="119,90", day=None, category=None, contact="",
          repeat="none", times=12, paid=False):
    form.kind_group.button(["expense", "income", "transfer"].index(kind)).click()
    form.desc.setText(desc)
    form.amount.setText(amount)
    d = date.today()
    form.due.setDate(QDate(d.year, d.month, day or d.day))
    if category:
        form.category.setCurrentIndex(form.category.findText(category))
    form.contact.setCurrentText(contact)
    form.repeat.setCurrentIndex(form.repeat.findData(repeat))
    form.times.setValue(times)
    form.paid.setChecked(paid)


def _names(page):
    return [e.description for e in page.model.rows]


def test_lista_do_mes_e_totais(window):
    page = _page(window)
    assert set(_names(page)) >= {"Salário", "Aluguel", "Mercado"}
    assert page.tot_rec.text() == "R$ 0,00"                    # salário já recebido
    assert page.tot_pay.text().startswith("R$ 2.")             # aluguel + luz + mercado em aberto


def test_novo_lancamento_pelo_formulario(window, qtbot):
    page = _page(window)
    window.new_entry()
    form = page.form
    assert page.form_scroll.isVisible() and form.title.text() == "Novo lançamento"
    assert form.category.currentText() == "Sem categoria"     # não escolhe categoria sozinho
    form.save_btn.click()
    assert "maior que zero" in form.error.text()               # validação aparece no formulário
    form.amount.setText("10")
    form.save_btn.click()
    assert "descrição" in form.error.text()
    _fill(form, category="Moradia › Internet e telefone", contact="Vivo")
    form.save_btn.click()
    assert not page.form_scroll.isVisible() and "Internet" in _names(page)


def test_parcelado_mostra_previa_e_cria_parcelas(window):
    page = _page(window)
    window.new_entry()
    _fill(page.form, desc="Geladeira", amount="1.000,00", repeat="installments", times=3)
    assert page.form.repeat_preview.text().startswith("3 parcelas de R$ 333,33")
    assert "a 1ª com R$ 333,34" in page.form.repeat_preview.text()
    assert page.form.amount_lbl.label.text() == "Valor total"
    page.form.save_btn.click()
    page._shift_month(2)
    assert any(e.description == "Geladeira" and e.installment == "3/3" for e in page.model.rows)


def test_transferencia_entre_contas(window):
    with db.Session() as s:
        accounts.create(s, window.profile.id, name="Carteira", kind="cash", opening_balance=D(0))
    page = _page(window)
    window.new_entry()
    form = page.form
    form.kind_group.button(2).click()
    assert not form.category.isVisible() and form.dest.isVisible()
    _fill(form, kind="transfer", desc="Saque", amount="200", paid=True)
    form.account.setCurrentIndex(form.account.findText("Nubank"))
    form.dest.setCurrentIndex(form.dest.findText("Carteira"))
    form.save_btn.click()
    with db.Session() as s:
        saldos = {a.name: a.balance for a in accounts.list_accounts(s, window.profile.id)}
    assert saldos["Carteira"] == D("200.00")


def test_editar_serie_este_e_os_proximos(window, dialogs):
    page = _page(window)
    aluguel = next(e for e in page.model.rows if e.description == "Aluguel")
    page.edit_entry(aluguel)
    assert "se repete" in page.form.series_info.text()
    page.form.amount.setText("1.650,00")
    dialogs.choice = "Este e os próximos"
    page.form.save_btn.click()
    assert any("série" in t for t in dialogs.shown)            # perguntou o escopo
    from finora.models import Entry
    with db.Session() as s:
        valores = [e.amount for e in s.query(Entry).filter_by(description="Aluguel").order_by(Entry.due_date)]
    assert valores == [D("1650.00")] * 3


def test_filtros_e_busca(window, qtbot):
    page = _page(window)
    page.filter_group.button(4).click()                         # Pagos
    assert _names(page) == ["Salário"]
    page.filter_group.button(2).click()                         # A pagar
    assert "Salário" not in _names(page) and "Mercado" in _names(page)
    page.filter_group.button(0).click()
    page.search.setText("merc")
    assert _names(page) == ["Mercado"]
    page.search.clear()


def test_marcar_como_pago_e_excluir(window, dialogs):
    page = _page(window)
    mercado = next(e for e in page.model.rows if e.description == "Mercado")
    page._toggle_paid(mercado)
    assert next(e for e in page.model.rows if e.description == "Mercado").is_paid
    page._delete(next(e for e in page.model.rows if e.description == "Mercado"))
    assert "Mercado" not in _names(page)


def test_formulario_ocupa_a_tela_em_janela_estreita(window, qtbot):
    page = _page(window)
    window.resize(800, 480)
    qtbot.wait(20)
    window.new_entry()
    qtbot.wait(20)
    assert page.form_scroll.isVisible() and not page.left.isVisible()
    page.form.cancel_btn.click()
    assert page.left.isVisible()


def test_filtro_por_conta_e_categoria(window):
    from finora.services import accounts as acc_svc
    with db.Session() as s:
        cash = acc_svc.create(s, window.profile.id, name="Carteira", kind="cash", opening_balance=D(0))
    page = _page(window)
    window.new_entry()
    _fill(page.form, desc="Pão", amount="12,00", category="Alimentação › Supermercado")
    page.form.account.setCurrentIndex(page.form.account.findData(cash))
    page.form.save_btn.click()
    page.account_filter.setCurrentIndex(page.account_filter.findData(cash))
    page.account_filter.activated.emit(page.account_filter.currentIndex())
    assert _names(page) == ["Pão"] and page.clear_filters.isVisible()
    page._clear_filters()
    i = page.category_filter.findText("Moradia")                       # grupo inclui subcategorias
    page.category_filter.setCurrentIndex(i)
    page.category_filter.activated.emit(i)
    assert set(_names(page)) == {"Aluguel", "Conta de luz"}
    page._clear_filters()
    assert not page.clear_filters.isVisible() and "Pão" in _names(page)


def test_ordenar_por_coluna(window):
    from finora.ui.entries_page import C_DESC, C_VALUE
    from PySide6.QtCore import Qt
    page = _page(window)
    page.table.sortByColumn(C_DESC, Qt.AscendingOrder)
    assert _names(page) == sorted(_names(page), key=str.lower)
    page.table.sortByColumn(C_VALUE, Qt.DescendingOrder)
    assert page.model.rows[0].description == "Salário"                # maior valor (receita) primeiro
    page.refresh()                                                      # ordenação continua após recarregar
    assert page.model.rows[0].description == "Salário"


def test_duplicar_abre_formulario_preenchido(window):
    page = _page(window)
    mercado = next(e for e in page.model.rows if e.description == "Mercado")
    page.duplicate_entry(mercado)
    f = page.form
    assert f.title.text() == "Novo lançamento (cópia)" and f.editing is None
    assert f.desc.text() == "Mercado" and f.amount.text() == "640,10"
    assert f.category.currentText() == "Alimentação › Supermercado"
    f.save_btn.click()
    assert _names(page).count("Mercado") == 2


def test_pagar_varios_selecionados(window, qtbot):
    from PySide6.QtCore import QItemSelectionModel
    page = _page(window)
    page.table.clearSelection()
    sm = page.table.selectionModel()
    for r, e in enumerate(page.model.rows):
        if e.description in ("Mercado", "Conta de luz", "Salário"):
            sm.select(page.model.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert page.sel_bar.isVisible() and page.sel_lbl.text().startswith("3 selecionados")
    assert page.pay_sel.text() == "Marcar 2 como pagos"                # salário já recebido fica de fora
    page.pay_sel.click()
    assert next(e for e in page.model.rows if e.description == "Mercado").is_paid
    assert next(e for e in page.model.rows if e.description == "Conta de luz").is_paid
