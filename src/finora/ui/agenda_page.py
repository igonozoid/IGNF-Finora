"""Tela Agenda (módulo "agenda", decisão D4): lista de tarefas ou calendário do mês, com o cadastro ao lado."""
from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCalendarWidget, QCheckBox, QComboBox, QCompleter, QDateEdit, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core.db import Session
from finora.services import agenda, contacts
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, field_label

PANEL_W = 300
COLS = ["", "DATA", "TAREFA", "CONTATO", "REPETE"]
KIND_ICON = {"task": "○", "done": "✓", "birthday": "🎂", "important": "★"}


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class TaskForm(QFrame):
    saved = Signal(str, int)

    def __init__(self, profile: Profile, t: dict):
        super().__init__(objectName="card")
        self.profile, self.t = profile, t
        self.current: agenda.TaskView | None = None
        self.setFixedWidth(PANEL_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(theme.SP_M)
        self.heading = QLabel(objectName="sectionTitle")
        lay.addWidget(self.heading)
        self.title = QLineEdit(maxLength=200, placeholderText="Ex.: pagar o IPVA, ligar para a Enel")
        lay.addWidget(field_label("O que fazer", t))
        lay.addWidget(self.title)
        self.has_date = QCheckBox("Tem data")
        self.due = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.due.setFont(theme.mono_font())
        row = QHBoxLayout()
        row.addWidget(self.has_date)
        row.addWidget(self.due, 1)
        lay.addLayout(row)
        self.recurrence = QComboBox()
        for k, label in agenda.RECURRENCES.items():
            self.recurrence.addItem(label, k)
        self.day = QSpinBox(minimum=0, maximum=31, specialValueText="mesmo dia")
        self.day.setToolTip("Dia do mês fixo (mensal em diante). 31 vira o último dia em mês mais curto.")
        rrow = QHBoxLayout()
        rrow.addWidget(self.recurrence, 1)
        rrow.addWidget(self.day)
        lay.addWidget(field_label("Repete", t, "Concluir uma tarefa que se repete cria a próxima sozinha."))
        lay.addLayout(rrow)
        self.contact = QComboBox(editable=True)
        self.contact.setInsertPolicy(QComboBox.NoInsert)
        self.contact.lineEdit().setPlaceholderText("Opcional")
        self.contact.completer().setFilterMode(Qt.MatchContains)
        self.contact.completer().setCompletionMode(QCompleter.PopupCompletion)
        lay.addWidget(field_label("Contato", t))
        lay.addWidget(self.contact)
        self.entry = QComboBox()
        lay.addWidget(field_label("Lançamento", t, "Opcional: a conta a pagar ou a receber de que a tarefa trata."))
        lay.addWidget(self.entry)
        self.notes = QPlainTextEdit(placeholderText="Observações (opcional)")
        self.notes.setMaximumHeight(90)
        lay.addWidget(self.notes)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        self.save_btn = button("Salvar", "primary")
        self.done_btn = button("Concluir", "secondary", t, "fa6s.check", "fg")
        self.delete_btn = button("Excluir", "danger")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.done_btn)
        btns.addStretch(1)
        btns.addWidget(self.delete_btn)
        lay.addLayout(btns)
        lay.addStretch(1)
        self.has_date.toggled.connect(self.due.setEnabled)
        self.recurrence.currentIndexChanged.connect(self._recurrence_changed)
        self.save_btn.clicked.connect(self.save)
        self.done_btn.clicked.connect(self.toggle_done)
        self.delete_btn.clicked.connect(self.delete)
        self.title.returnPressed.connect(self.save)

    def _recurrence_changed(self):
        k = self.recurrence.currentData()
        self.day.setVisible(k in ("monthly", "bimonthly", "quarterly", "semiannual", "yearly"))
        if k != "none":
            self.has_date.setChecked(True)

    def _load_lists(self, keep_entry: int | None):
        with Session() as s:
            names = contacts.names(s, self.profile.id)
            entries = agenda.entry_choices(s, self.profile.id, keep_entry)
        self.contact.clear()
        self.contact.addItem("")
        self.contact.addItems(names)
        self.entry.clear()
        self.entry.addItem("— nenhum —", None)
        for eid, label in entries:
            self.entry.addItem(label, eid)

    def open_new(self, day: date | None = None):
        self.current = None
        self._load_lists(None)
        self.heading.setText("Nova tarefa")
        self.title.clear()
        self.has_date.setChecked(True)
        self.due.setDate(_qdate(day or date.today()))
        self.recurrence.setCurrentIndex(0)
        self.day.setValue(0)
        self.contact.setCurrentText("")
        self.notes.clear()
        self.done_btn.hide()
        self.delete_btn.hide()
        self._recurrence_changed()
        self._error(None)
        self.title.setFocus()

    def open_task(self, task: agenda.TaskView):
        self.current = task
        self._load_lists(task.entry_id)
        self.heading.setText("Tarefa feita" if task.status == "done" else "Tarefa")
        self.title.setText(task.title)
        self.has_date.setChecked(task.due_date is not None)
        self.due.setEnabled(task.due_date is not None)
        self.due.setDate(_qdate(task.due_date or date.today()))
        self.recurrence.setCurrentIndex(max(0, self.recurrence.findData(task.recurrence)))
        self.day.setValue(task.recurrence_day or 0)
        self.contact.setCurrentText(task.contact)
        self.entry.setCurrentIndex(max(0, self.entry.findData(task.entry_id)))
        self.notes.setPlainText(task.notes)
        self.done_btn.setText("Reabrir" if task.status == "done" else "Concluir")
        self.done_btn.show()
        self.delete_btn.show()
        self._recurrence_changed()
        self._error(None)

    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def save(self):
        try:
            with Session() as s:
                tid = agenda.save(s, self.profile.id, self.current.id if self.current else None,
                                  title=self.title.text(),
                                  due_date=self.due.date().toPython() if self.has_date.isChecked() else None,
                                  notes=self.notes.toPlainText(), recurrence=self.recurrence.currentData(),
                                  recurrence_day=self.day.value() or None, contact=self.contact.currentText(),
                                  entry_id=self.entry.currentData())
        except ValueError as e:
            self._error(str(e))
            return
        self.saved.emit("Tarefa salva.", tid)

    def toggle_done(self):
        task = self.current
        if task is None:
            return
        with Session() as s:
            if task.status == "done":
                agenda.reopen(s, task.id)
                msg = "Tarefa reaberta."
            else:
                nxt = agenda.complete(s, task.id)
                msg = "Tarefa concluída." + (" A próxima já está na agenda." if nxt else "")
        self.saved.emit(msg, task.id)

    def delete(self):
        if self.current is None:
            return
        with Session() as s:
            agenda.delete(s, self.current.id)
        self.current = None
        self.saved.emit("Tarefa excluída.", 0)


class AgendaPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.status = "open"
        self.items: list[agenda.TaskView] = []

        self.filter_group = QButtonGroup(self, exclusive=True)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        for i, (k, label) in enumerate(agenda.STATUS.items()):
            b = QPushButton(label, checkable=True, checked=(k == "open"))
            b.setProperty("variant", "pill")
            b.setProperty("key", k)
            b.setProperty("label", label)
            b.setCursor(Qt.PointingHandCursor)
            self.filter_group.addButton(b, i)
            bar.addWidget(b)
        self.search = QLineEdit(placeholderText="Buscar tarefa ou contato…", clearButtonEnabled=True)
        self.search.setMaximumWidth(220)
        bar.addWidget(self.search)
        bar.addStretch(1)
        self.view_btn = button("Calendário", "secondary", t, "fa6s.calendar-days", "fg")
        self.view_btn.setCheckable(True)
        self.new_btn = button("Nova tarefa", "primary", t, "fa6s.plus", "on_acc")
        bar.addWidget(self.view_btn)
        bar.addWidget(self.new_btn)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        for col, w in ((0, 28), (1, 90), (3, 180), (4, 140)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            hdr.resizeSection(col, w)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.upcoming = QLabel(wordWrap=True)
        self.upcoming.setProperty("role", "muted")
        list_box = QWidget()
        ll = QVBoxLayout(list_box)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.table, 1)
        ll.addWidget(self.empty, 1)
        ll.addWidget(self.upcoming)

        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.day_list = QListWidget()
        self.day_list.setMaximumHeight(160)
        cal_box = QWidget()
        cl = QVBoxLayout(cal_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.calendar, 1)
        cl.addWidget(self.day_list)
        self.views = QStackedWidget()
        self.views.addWidget(list_box)
        self.views.addWidget(cal_box)

        self.form = TaskForm(profile, t)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addLayout(bar)
        left.addWidget(self.views, 1)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addLayout(left, 1)
        root.addWidget(self.form)

        self.filter_group.idClicked.connect(self._filter)
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.table.currentCellChanged.connect(lambda r, *_a: self._selected(r))
        self.table.cellClicked.connect(self._clicked)
        self.new_btn.clicked.connect(lambda: self.form.open_new(self._day() if self.views.currentIndex() else None))
        self.view_btn.toggled.connect(self._toggle_view)
        self.calendar.currentPageChanged.connect(lambda *_a: self._paint_month())
        self.calendar.selectionChanged.connect(self._fill_day)
        self.day_list.itemDoubleClicked.connect(self._open_day_item)
        self.form.saved.connect(self._saved)

    # ----- dados -----
    def _filter(self, i: int):
        self.status = self.filter_group.button(i).property("key")
        self.refresh()

    def refresh(self, select_id: int | None = None):
        today = date.today()
        with Session() as s:
            self.items = agenda.list_tasks(s, self.profile.id, self.status, self.search.text())
            n = agenda.counts(s, self.profile.id)
            soon = [i for i in agenda.occurrences(s, self.profile.id, today, today + timedelta(days=30))
                    if i.kind in ("birthday", "important")]
        for b in self.filter_group.buttons():
            b.setText(f"{b.property('label')} ({n[b.property('key')]})")
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        row_sel = -1
        for r, task in enumerate(self.items):
            late = task.late(today)
            cells = ["✓" if task.status == "done" else "", f"{task.due_date:%d/%m/%Y}" if task.due_date else "—",
                     task.title + (f"  · {task.entry_label}" if task.entry_label else ""), task.contact,
                     task.recurrence_label]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 1:
                    it.setFont(theme.mono_font())
                if late and c in (1, 2):
                    it.setForeground(QColor(self.t["neg"]))
                elif task.status == "done":
                    it.setForeground(QColor(self.t["mut"]))
                self.table.setItem(r, c, it)
            self.table.item(r, 0).setToolTip("Concluir" if task.status != "done" else "Reabrir")
            if task.id == select_id:
                row_sel = r
        if row_sel >= 0:
            self.table.selectRow(row_sel)
        self.table.blockSignals(False)
        has = bool(self.items)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        self.empty.setText("Nada por aqui." if self.search.text().strip() or self.status != "open" else
                           "Nenhuma tarefa a fazer.\nUse \"Nova tarefa\" para anotar o que precisa ser feito.")
        self.upcoming.setText("Próximos 30 dias: " + " · ".join(f"{i.text} ({i.day:%d/%m})" for i in soon)
                              if soon else "")
        self.upcoming.setVisible(bool(soon))
        if row_sel >= 0:
            self.form.open_task(self.items[row_sel])
        elif self.form.current is None or select_id == 0:
            self.form.open_new()
        if self.views.currentIndex():
            self._paint_month()

    def _selected(self, row: int):
        if 0 <= row < len(self.items):
            self.form.open_task(self.items[row])

    def _clicked(self, row: int, col: int):
        """Clique na 1ª coluna conclui (ou reabre) direto da lista."""
        if col == 0 and 0 <= row < len(self.items):
            self.form.open_task(self.items[row])
            self.form.toggle_done()

    def _saved(self, msg: str, tid: int):
        self.message.emit(msg)
        self.refresh(select_id=tid)

    def apply_theme(self, t: dict):
        self.t = self.form.t = t
        if self.isVisible():
            self.refresh()

    # ----- calendário -----
    def _toggle_view(self, on: bool):
        self.views.setCurrentIndex(1 if on else 0)
        self.view_btn.setText("Lista" if on else "Calendário")
        if on:
            self._paint_month()

    def _day(self) -> date:
        return self.calendar.selectedDate().toPython()

    def _month_items(self) -> list[agenda.DayItem]:
        y, m = self.calendar.yearShown(), self.calendar.monthShown()
        first = date(y, m, 1)
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        with Session() as s:
            return agenda.occurrences(s, self.profile.id, first, last)

    def _paint_month(self):
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())          # limpa as marcas anteriores
        self._month = self._month_items()
        for item in self._month:
            fmt = QTextCharFormat()
            fmt.setFontWeight(700)
            fmt.setForeground(QColor(self.t["acc"] if item.kind != "done" else self.t["mut"]))
            self.calendar.setDateTextFormat(_qdate(item.day), fmt)
        self._fill_day()

    def _fill_day(self):
        day = self._day()
        self.day_list.clear()
        self._day_items = [i for i in getattr(self, "_month", []) if i.day == day]
        for i in self._day_items:
            self.day_list.addItem(f"{KIND_ICON[i.kind]}  {i.text}")
        if not self._day_items:
            self.day_list.addItem(f"Nada em {day:%d/%m/%Y}.")

    def _open_day_item(self, _it):
        row = self.day_list.currentRow()
        if 0 <= row < len(self._day_items) and self._day_items[row].task_id:
            with Session() as s:
                task = next((x for x in agenda.list_tasks(s, self.profile.id, "all")
                             if x.id == self._day_items[row].task_id), None)
            if task is not None:
                self.form.open_task(task)
