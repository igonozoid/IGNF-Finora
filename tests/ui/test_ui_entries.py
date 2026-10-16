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


def test_parcelado_a_cada_15_dias(window):
    page = _page(window)
    window.new_entry()
    form = page.form
    assert form.every.isHidden()                                     # só aparece no parcelado
    _fill(form, desc="Trator", amount="1.000,00", day=1, repeat="installments", times=4)
    assert not form.every.isHidden() and form.every.currentData() == "monthly"
    form.every.setCurrentIndex(form.every.findData("biweekly"))
    assert "4 parcelas de R$ 250,00, a cada 15 dias, até" in form.repeat_preview.text()
    form.save_btn.click()
    from finora.models import Entry
    with db.Session() as s:
        dues = [e.due_date for e in s.query(Entry).filter_by(description="Trator").order_by(Entry.due_date)]
    first = dues[0]
    assert [(d - first).days for d in dues] == [0, 15, 30, 45]
    window.new_entry()
    assert form.every.currentData() == "monthly" and form.every.isHidden()   # formulário novo volta ao padrão
    form.repeat.setCurrentIndex(form.repeat.findData("quarterly"))
    assert form.every.isHidden() and form.repeat_preview.text().startswith("12 lançamentos, o último em")
    form.cancel_btn.click()


def test_parcelado_com_documento_e_competencia_da_compra(window):
    page = _page(window)
    window.new_entry()
    form = page.form
    assert form.competence_row.isHidden()                               # só no parcelado
    _fill(form, desc="Plantadeira", amount="3.000,00", day=1, repeat="installments", times=3)
    assert not form.competence_row.isHidden() and not form.competence_first.isChecked()
    form.doc.setText("NF-778")
    form.competence_first.setChecked(True)
    form.save_btn.click()
    from finora.models import Entry
    with db.Session() as s:
        rows = s.query(Entry).filter_by(description="Plantadeira").order_by(Entry.due_date).all()
        assert [e.document_no for e in rows] == ["NF-778 1/3", "NF-778 2/3", "NF-778 3/3"]
        assert len({e.competence_date for e in rows}) == 1 and len({e.due_date for e in rows}) == 3
    window.new_entry()
    assert not form.competence_first.isChecked()                         # formulário novo volta ao padrão
    form.cancel_btn.click()


def test_baixa_com_juros_pela_janela(window, monkeypatch):
    from finora.ui.payment_dialog import PaymentDialog
    page = _page(window)
    mercado = next(e for e in page.model.rows if e.description == "Mercado")
    seen = {}

    def fake_exec(dlg):
        assert dlg.windowTitle() == "Pagar" and dlg.amount.text() == "640,10"
        assert dlg.difference.isHidden()
        dlg.amount.setText("700,00")
        seen["diff"] = dlg.difference.text()
        dlg.note.setText("Juros e multa")
        dlg.confirm()

    monkeypatch.setattr(PaymentDialog, "exec", fake_exec)
    page._toggle_paid(mercado)
    assert seen["diff"] == "A mais que o previsto (juros/multa): R$ 59,90"
    e = next(e for e in page.model.rows if e.description == "Mercado")
    assert e.is_paid and e.amount == D("700.00") and e.original_amount == D("640.10")
    assert e.notes.endswith("Juros e multa")
    # cancelar a janela não marca nada
    luz = next(e for e in page.model.rows if e.description == "Conta de luz")
    monkeypatch.setattr(PaymentDialog, "exec", lambda dlg: dlg.reject())
    page._toggle_paid(luz)
    assert not next(e for e in page.model.rows if e.description == "Conta de luz").is_paid


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


def test_marcar_como_pago_e_excluir(window, dialogs, monkeypatch):
    from finora.ui.payment_dialog import PaymentDialog
    monkeypatch.setattr(PaymentDialog, "exec", lambda dlg: dlg.confirm())   # confirma a baixa como veio
    page = _page(window)
    mercado = next(e for e in page.model.rows if e.description == "Mercado")
    page._toggle_paid(mercado)
    assert next(e for e in page.model.rows if e.description == "Mercado").is_paid
    page._delete(next(e for e in page.model.rows if e.description == "Mercado"))
    assert "Mercado" not in _names(page)
    assert not page.undo_bar.isHidden()                      # "Foi para a lixeira. Desfazer"
    page.undo_delete()
    assert "Mercado" in _names(page) and page.undo_bar.isHidden()


def test_excluir_serie_pergunta_as_opcoes_do_mcc(window, dialogs):
    from finora.models import Entry
    page = _page(window)
    aluguel = next(e for e in page.model.rows if e.description == "Aluguel")      # série de 3, em aberto
    dialogs.choice = None                                                       # cancela
    page._delete(aluguel)
    assert any("série de 3 lançamentos (3 em aberto)" in t for t in dialogs.shown)
    assert "Aluguel" in _names(page)
    dialogs.choice = "Todos em aberto (3)"
    page._delete(aluguel)
    with db.Session() as s:
        assert s.query(Entry).filter_by(description="Aluguel").count() == 0         # foram para a lixeira
    assert "Aluguel" not in _names(page) and not page.undo_bar.isHidden()
    page.undo_delete()                                                          # Desfazer traz os 3 de volta
    with db.Session() as s:
        assert s.query(Entry).filter_by(description="Aluguel").count() == 3


def test_levar_para_outra_entidade(plus, window, monkeypatch):
    from finora.models import Entry
    from finora.services import entity_admin
    from finora.ui.move_dialog import MoveDialog
    page = _page(window)
    assert not page._other_entities()                                     # uma entidade só: a ação não aparece
    with db.Session() as s:
        other = entity_admin.create(s, name="Padaria Sol")
    assert page._other_entities()
    mercado = next(e for e in page.model.rows if e.description == "Mercado")

    def fake_exec(dlg):
        assert dlg.entity.currentText() == "Padaria Sol" and dlg.account.currentText() == "Conta principal"
        dlg.confirm()

    monkeypatch.setattr(MoveDialog, "exec", fake_exec)
    msgs = []
    page.message.connect(msgs.append)
    page.move_to_entity([mercado])
    assert "Mercado" not in _names(page)
    assert msgs[-1].startswith("1 lançamento levado para Padaria Sol")
    with db.Session() as s:
        assert s.query(Entry).filter_by(description="Mercado").one().entity_id == other


def test_coluna_observacoes_opcional(window, qtbot):
    from PySide6.QtCore import Qt
    from finora.core import settings
    from finora.services import entries as svc
    from finora.ui.entries_page import C_NOTES
    page = _page(window)
    window.resize(1400, 800)
    qtbot.wait(20)
    assert page.table.isColumnHidden(C_NOTES)                            # desligada por padrão
    mercado = next(e for e in page.model.rows if e.description == "Mercado")
    with db.Session() as s:
        d = svc.EntryData(kind=mercado.kind, description="Mercado", amount=mercado.amount,
                          due_date=mercado.due_date, account_id=mercado.account_id,
                          category_id=mercado.category_id, contact=mercado.contact, notes="Compra do mês\nCartão")
        svc.update(s, mercado.id, d)
    page.refresh()
    page.set_notes_column(True)
    assert not page.table.isColumnHidden(C_NOTES) and settings.get_entries_notes_column()
    row = next(i for i, e in enumerate(page.model.rows) if e.description == "Mercado")
    assert page.model.data(page.model.index(row, C_NOTES)) == "Compra do mês Cartão"          # uma linha só
    assert page.model.data(page.model.index(row, C_NOTES), Qt.ToolTipRole) == "Compra do mês\nCartão"
    page.table.sortByColumn(C_NOTES, Qt.DescendingOrder)
    assert page.model.rows[0].description == "Mercado"                   # o único com observação vem antes
    window.resize(800, 600)                                              # tela estreita: some primeiro
    qtbot.wait(20)
    assert page.table.isColumnHidden(C_NOTES)
    window.resize(1400, 800)
    qtbot.wait(20)
    page.set_notes_column(False)
    assert page.table.isColumnHidden(C_NOTES) and not settings.get_entries_notes_column()


def test_repetir_no_mes_seguinte_pelo_menu(window, dialogs):
    from finora.models import Entry
    page = _page(window)
    mercado = next(e for e in page.model.rows if e.description == "Mercado")
    dialogs.answer_yes = False                                                # cancelou: nada muda
    page.repeat_next_month([mercado])
    with db.Session() as s:
        assert s.query(Entry).filter_by(description="Mercado").count() == 1
    dialogs.answer_yes = True
    msgs = []
    page.message.connect(msgs.append)
    page.repeat_next_month([mercado])
    with db.Session() as s:
        dues = [e.due_date for e in s.query(Entry).filter_by(description="Mercado").order_by(Entry.due_date)]
    assert len(dues) == 2 and (dues[1].month - dues[0].month) % 12 == 1
    assert msgs[-1] == "1 lançamento repetido no mês seguinte."


def test_lixeira_restaura(window, monkeypatch):
    from finora.ui.trash_dialog import TrashDialog
    page = _page(window)
    page._delete(next(e for e in page.model.rows if e.description == "Mercado"))

    def fake_exec(dlg):
        assert [i.description for i in dlg.items] == ["Mercado"] and not dlg.restore_btn.isEnabled()
        dlg.search.setText("nada disso")
        assert dlg.table.isHidden() and dlg.empty.text() == "Nada encontrado."
        dlg.search.clear()
        dlg.table.selectRow(0)
        dlg.restore_selected()
        assert dlg.items == [] and dlg.empty.text() == "A lixeira está vazia."
        return 0

    monkeypatch.setattr(TrashDialog, "exec", fake_exec)
    page.trash_btn.click()
    assert "Mercado" in _names(page)


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


def test_mais_filtros_ano_todo_e_limpar(window, qtbot):
    page = _page(window)
    page.more_btn.click()
    assert not page.more_w.isHidden()
    page.period_box.setCurrentIndex(page.period_box.findData("all"))
    page.refresh()
    assert len(page.model.rows) > 4 and page.clear_filters.isVisible()          # todos os meses do aluguel
    page.kind_box.setCurrentIndex(page.kind_box.findData("income"))
    page.refresh()
    assert {e.kind for e in page.model.rows} == {"income"} and "•" in page.more_btn.text()
    page.clear_filters.click()
    assert page.period_box.currentData() == "month" and page.kind_box.currentData() == ""


def test_observacoes_no_formulario_lista_copia_e_exportacao(window):
    from PySide6.QtCore import Qt
    from finora.ui.entries_page import C_DESC
    page = _page(window)
    window.new_entry()
    form = page.form
    assert form.notes.toPlainText() == ""
    _fill(form, desc="Conserto do portão", amount="350,00")
    form.notes.setPlainText("Serralheria do Zé\nGarantia de 90 dias")
    form.save_btn.click()
    e = next(e for e in page.model.rows if e.description == "Conserto do portão")
    assert e.notes == "Serralheria do Zé\nGarantia de 90 dias"
    row = page.model.rows.index(e)
    assert "Observações: Serralheria do Zé" in page.model.data(page.model.index(row, C_DESC), Qt.ToolTipRole)
    page.edit_entry(e)                                                   # editar mostra e salva a observação
    assert form.notes.toPlainText() == e.notes
    form.notes.setPlainText("Garantia até janeiro")
    form.save_btn.click()
    e = next(e for e in page.model.rows if e.description == "Conserto do portão")
    assert e.notes == "Garantia até janeiro"
    page.duplicate_entry(e)                                              # a cópia leva a observação
    assert form.notes.toPlainText() == "Garantia até janeiro"
    form.cancel_btn.click()
    window.new_entry()                                                   # lançamento novo começa sem
    assert form.notes.toPlainText() == ""
    form.cancel_btn.click()
    sheet = page.export_sheet()
    assert sheet.headers[-1] == "Observações"
    assert any(r[-1] == "Garantia até janeiro" for r in sheet.rows)
