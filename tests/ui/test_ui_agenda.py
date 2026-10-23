"""Tela Agenda (módulo "agenda", decisão D4)."""
from datetime import date

from PySide6.QtCore import QDate

from finora.core import db
from finora.services import agenda, contacts, modules


def _ligar(window):
    with db.Session() as s:
        modules.set_enabled(s, window.profile.id, "agenda", True)
    window._apply_access()


def test_agenda_so_aparece_com_o_modulo(window):
    assert "agenda" not in window.visible_keys
    _ligar(window)
    assert "agenda" in window.visible_keys


def test_criar_concluir_e_recorrencia(window):
    _ligar(window)
    window.go_to("agenda")
    page = window.page("agenda")
    assert "Nenhuma tarefa" in page.empty.text()
    form = page.form
    form.open_new()
    form.title.setText("Pagar o aluguel")
    form.due.setDate(QDate(2026, 10, 10))
    form.recurrence.setCurrentIndex(form.recurrence.findData("monthly"))
    assert not form.day.isHidden()
    form.contact.setCurrentText("Imobiliária")
    form.save_btn.click()
    assert [t.title for t in page.items] == ["Pagar o aluguel"]
    assert page.table.item(0, 4).text() == "Todo mês" and page.table.item(0, 3).text() == "Imobiliária"
    page._clicked(0, 0)                                            # concluir pela lista
    assert "A próxima já está na agenda" in window.statusBar().currentMessage()
    assert [t.due_date for t in page.items] == [date(2026, 11, 10)]
    page.filter_group.button(2).click()                            # Feitas
    assert [t.title for t in page.items] == ["Pagar o aluguel"] and page.items[0].status == "done"


def test_erro_e_calendario(window):
    _ligar(window)
    eid = window.profile.id
    with db.Session() as s:
        contacts.create(s, eid, name="Maria", details={"birthday": f"{date.today():%d/%m}/1980"})
        agenda.save(s, eid, title="Reunião", due_date=date.today())
    window.go_to("agenda")
    page = window.page("agenda")
    assert "Aniversário de Maria" in page.upcoming.text()
    page.form.open_new()
    page.form.save_btn.click()
    assert "precisa ser feito" in page.form.error.text()
    page.view_btn.setChecked(True)
    page.calendar.setSelectedDate(QDate.currentDate())
    texts = [page.day_list.item(i).text() for i in range(page.day_list.count())]
    assert any("Aniversário de Maria" in x for x in texts) and any("Reunião" in x for x in texts)
