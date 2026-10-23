"""Tela RH (módulo "hr", decisão D4): funcionários com o total da folha; ao lado, perfil, histórico e custo."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import hr
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, field_label

R = Qt.AlignRight | Qt.AlignVCenter
COLS = [("FUNCIONÁRIO", None), ("FUNÇÃO", 150), ("TIPO", 110), ("ADMISSÃO", 90), ("SALÁRIO", 110),
        ("BENEFÍCIOS", 100), ("TOTAL", 110)]
STATUS = {"active": "Ativos", "terminated": "Desligados", "all": "Todos"}
PANEL_W = 340


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _parse(text: str, what: str) -> Decimal | None:
    if not text.strip():
        return None
    try:
        return money.parse(text)
    except ValueError:
        raise ValueError(f"{what} inválido. Ex.: 1.518,00") from None


def _date_edit(d: date | None) -> tuple[QCheckBox, QDateEdit]:
    on = QCheckBox()
    edit = QDateEdit(_qdate(d or date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
    edit.setFont(theme.mono_font())
    on.setChecked(d is not None)
    edit.setEnabled(d is not None)
    on.toggled.connect(edit.setEnabled)
    return on, edit


class RecordDialog(QDialog):
    """Um registro do histórico: reajuste de salário, férias, 13º ou benefício."""

    def __init__(self, parent, kind: str, rec: hr.RecordView | None = None):
        super().__init__(parent)
        self.kind, self.rec = kind, rec
        self.setWindowTitle(hr.KINDS[kind])
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        self.fields: dict[str, QWidget] = {}
        labels = {"salary": [("day", "Vigência"), ("amount", "Salário nominal (carteira)"),
                             ("net_amount", "Líquido pago")],
                  "vacation": [("period", "Período aquisitivo"), ("day", "Início do gozo"),
                               ("end_day", "Fim do gozo"), ("amount", "Valor pago")],
                  "thirteenth": [("period", "Ano"), ("day", "Pagamento"), ("amount", "Valor pago")],
                  "benefit": [("name", "Benefício (ex.: Unimed)"), ("amount", "Valor por mês"),
                              ("active", "Em vigor")]}[kind]
        for row, (key, label) in enumerate(labels):
            grid.addWidget(QLabel(label), row, 0)
            if key in ("day", "end_day"):
                on, edit = _date_edit(getattr(rec, key) if rec else (date.today() if key == "day" else None))
                box = QHBoxLayout()
                box.addWidget(on)
                box.addWidget(edit, 1)
                grid.addLayout(box, row, 1)
                self.fields[key] = (on, edit)
            elif key == "active":
                w = QCheckBox(checked=rec.active if rec else True)
                grid.addWidget(w, row, 1)
                self.fields[key] = w
            else:
                value = getattr(rec, key) if rec else None
                if key in ("amount", "net_amount"):
                    text = money.fmt(value).split(" ", 1)[-1] if value is not None else ""
                else:
                    text = value or ""
                w = QLineEdit(text)
                if key in ("amount", "net_amount"):
                    w.setFont(theme.mono_font())
                    w.setAlignment(Qt.AlignRight)
                if key == "period":
                    w.setPlaceholderText("Ex.: 2025" if kind == "thirteenth" else "Ex.: 03/2025 a 02/2026")
                grid.addWidget(w, row, 1)
                self.fields[key] = w
        lay.addLayout(grid)
        self.notes = QLineEdit(rec.notes if rec else "", placeholderText="Observação (opcional)", maxLength=300)
        lay.addWidget(self.notes)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancelar", "secondary")
        self.ok_btn = button("Salvar", "primary")
        btns.addWidget(cancel)
        btns.addWidget(self.ok_btn)
        lay.addLayout(btns)
        cancel.clicked.connect(self.reject)

    def data(self) -> dict:
        out = {"kind": self.kind, "notes": self.notes.text()}
        for key, w in self.fields.items():
            if key in ("day", "end_day"):
                on, edit = w
                out[key] = edit.date().toPython() if on.isChecked() else None
            elif key == "active":
                out[key] = w.isChecked()
            elif key in ("amount", "net_amount"):
                out[key] = _parse(w.text(), "Valor")
            else:
                out[key] = w.text()
        return out


class EmployeePanel(QFrame):
    changed = Signal(str)

    def __init__(self, profile: Profile, t: dict):
        super().__init__(objectName="card")
        self.profile, self.t = profile, t
        self.contact_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(theme.SP_M)
        self.title = QLabel(objectName="sectionTitle", wordWrap=True)
        lay.addWidget(self.title)
        self.hint = QLabel("Escolha um funcionário na lista ou use \"Novo funcionário\".", wordWrap=True)
        self.hint.setProperty("role", "muted")
        lay.addWidget(self.hint)

        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(theme.SP_M)
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP_M)
        self.job = QLineEdit(maxLength=80, placeholderText="Ex.: Jardineiro(a)")
        self.staff = QComboBox()
        for k, label in hr.STAFF.items():
            self.staff.addItem(label, k)
        self.employment = QComboBox(editable=True)
        self.employment.addItems([""] + list(hr.EMPLOYMENT))
        self.union = QLineEdit(maxLength=120)
        self.workplace = QLineEdit(maxLength=120)
        self.inss = QLineEdit(placeholderText="Ex.: 8")
        self.hours = QLineEdit(placeholderText="Ex.: 220")
        self.initial = QLineEdit(placeholderText="0,00")
        for w in (self.inss, self.hours, self.initial):
            w.setFont(theme.mono_font())
            w.setAlignment(Qt.AlignRight)
        self.adm_on, self.adm = _date_edit(None)
        self.term_on, self.term = _date_edit(None)
        rows = [("Função", self.job), ("Categoria", self.staff), ("Vínculo", self.employment),
                ("Sindicato", self.union), ("Local de trabalho", self.workplace), ("INSS patronal (%)", self.inss),
                ("Horas por mês", self.hours), ("Salário inicial", self.initial)]
        for r, (label, w) in enumerate(rows):
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(w, r, 1)
        for r, (label, on, edit) in enumerate((("Admissão", self.adm_on, self.adm),
                                               ("Saída", self.term_on, self.term)), start=len(rows)):
            grid.addWidget(QLabel(label), r, 0)
            box = QHBoxLayout()
            box.addWidget(on)
            box.addWidget(edit, 1)
            grid.addLayout(box, r, 1)
        bl.addLayout(grid)
        self.notes = QPlainTextEdit(placeholderText="Observações (opcional)")
        self.notes.setMaximumHeight(60)
        bl.addWidget(self.notes)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        bl.addWidget(self.error)
        self.save_btn = button("Salvar perfil", "primary")
        bl.addWidget(self.save_btn, 0, Qt.AlignLeft)

        head = QHBoxLayout()
        head.addWidget(field_label("Histórico", t, "Reajustes de salário, férias, 13º e benefícios mensais.\n"
                                                   "Dois cliques numa linha para editar."), 1)
        self.add_kind = QComboBox()
        for k, label in hr.KINDS.items():
            self.add_kind.addItem(label, k)
        self.add_btn = button("Adicionar", "link", t, "fa6s.plus", "acc")
        self.del_btn = button("Remover", "link", t, "fa6s.trash-can", "mut")
        head.addWidget(self.add_kind)
        head.addWidget(self.add_btn)
        head.addWidget(self.del_btn)
        bl.addLayout(head)
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(["TIPO", "DATA", "DETALHE", "VALOR"])
        self.history.verticalHeader().hide()
        self.history.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.history.setMinimumHeight(140)
        bl.addWidget(self.history)
        self.cost_lbl = QLabel(wordWrap=True)
        self.cost_lbl.setTextFormat(Qt.RichText)
        bl.addWidget(field_label("Custo mensal estimado", t, "Salário atual + INSS patronal (alíquota do perfil),\n"
                                                              "FGTS 8% e provisões de 13º (1/12) e 1/3 de férias (1/36)."))
        bl.addWidget(self.cost_lbl)
        lay.addWidget(self.body)
        lay.addStretch(1)
        self.body.hide()
        self._records: list[hr.RecordView] = []
        self.save_btn.clicked.connect(self.save)
        self.add_btn.clicked.connect(lambda: self.edit_record(None))
        self.del_btn.clicked.connect(self.delete_record)
        self.history.cellDoubleClicked.connect(lambda r, _c: self.edit_record(r))

    def open(self, emp: hr.EmployeeView | None):
        self.contact_id = emp.contact_id if emp else None
        self.title.setText(emp.name if emp else "RH")
        self.hint.setVisible(emp is None)
        self.body.setVisible(emp is not None)
        if emp is None:
            return
        with Session() as s:
            p = hr.get_profile(s, emp.contact_id)
        self.job.setText(p["job_title"] or "")
        self.staff.setCurrentIndex(max(0, self.staff.findData(p["staff_category"])))
        self.employment.setCurrentText(p["employment_type"] or "")
        self.union.setText(p["union_name"] or "")
        self.workplace.setText(p["workplace"] or "")
        self.inss.setText(hr.fmt_rate(p["inss_rate"]))
        self.hours.setText(money.fmt(p["monthly_hours"]).split(" ", 1)[-1] if p["monthly_hours"] is not None else "")
        self.initial.setText(money.fmt(p["initial_salary"]).split(" ", 1)[-1]
                             if p["initial_salary"] is not None else "")
        for (on, edit), d in (((self.adm_on, self.adm), p["admission_date"]),
                              ((self.term_on, self.term), p["termination_date"])):
            on.setChecked(d is not None)
            edit.setDate(_qdate(d or date.today()))
        self.notes.setPlainText(p["notes"] or "")
        self._error(None)
        self._fill_history()

    def _fill_history(self):
        cur = self.profile.currency
        with Session() as s:
            self._records = hr.records(s, self.contact_id)
            cost = hr.cost(s, self.contact_id)
        self.history.setRowCount(len(self._records))
        for r, rec in enumerate(self._records):
            when = rec.day.strftime("%d/%m/%Y") if rec.day else ""
            if rec.kind == "vacation" and rec.day and rec.end_day:
                when += f" a {rec.end_day:%d/%m/%Y}"
            detail = {"salary": f"líquido {money.fmt(rec.net_amount, cur)}" if rec.net_amount is not None else "",
                      "vacation": rec.period and f"aquisitivo {rec.period}",
                      "thirteenth": rec.period, "benefit": rec.name + ("" if rec.active else " (encerrado)")}[rec.kind]
            cells = [hr.KINDS[rec.kind], when, " · ".join(x for x in (detail, rec.notes) if x),
                     money.fmt(rec.amount, cur) if rec.amount is not None else ""]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c in (1, 3):
                    it.setFont(theme.mono_font())
                if c == 3:
                    it.setTextAlignment(R)
                self.history.setItem(r, c, it)
        lines = "".join(f"<tr><td>{label}</td><td align='right'>{money.fmt(v, cur)}</td></tr>"
                        for label, v in cost.lines if v)
        self.cost_lbl.setText(f"<table width='100%'><tr><td>Salário atual</td><td align='right'>"
                              f"{money.fmt(cost.salary, cur)}</td></tr>{lines}<tr><td><b>Custo total</b></td>"
                              f"<td align='right'><b>{money.fmt(cost.total, cur)}</b></td></tr></table>")

    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def save(self):
        if self.contact_id is None:
            return
        try:
            rate = _parse(self.inss.text(), "INSS")
            data = dict(job_title=self.job.text(), staff_category=self.staff.currentData(),
                        employment_type=self.employment.currentText(), union_name=self.union.text(),
                        workplace=self.workplace.text(), inss_rate=rate / 100 if rate is not None else None,
                        monthly_hours=_parse(self.hours.text(), "Horas"),
                        initial_salary=_parse(self.initial.text(), "Salário"),
                        admission_date=self.adm.date().toPython() if self.adm_on.isChecked() else None,
                        termination_date=self.term.date().toPython() if self.term_on.isChecked() else None,
                        notes=self.notes.toPlainText())
            with Session() as s:
                hr.save_profile(s, self.profile.id, self.contact_id, **data)
        except ValueError as e:
            self._error(str(e))
            return
        self._error(None)
        self._fill_history()
        self.changed.emit("Perfil de RH salvo.")

    def edit_record(self, row: int | None):
        if self.contact_id is None:
            return
        rec = self._records[row] if row is not None and 0 <= row < len(self._records) else None
        dlg = RecordDialog(self, rec.kind if rec else self.add_kind.currentData(), rec)
        self.record_dialog = dlg                       # os testes de tela pegam o diálogo aberto

        def ok():
            try:
                with Session() as s:
                    hr.save_record(s, self.profile.id, self.contact_id, rec.id if rec else None, **dlg.data())
            except ValueError as e:
                dlg.error.setText(str(e))
                dlg.error.show()
                return
            dlg.accept()
        dlg.ok_btn.clicked.connect(ok)
        if dlg.exec():
            self._fill_history()
            self.changed.emit(f"{hr.KINDS[dlg.kind]} salvo no histórico.")

    def delete_record(self):
        row = self.history.currentRow()
        if not 0 <= row < len(self._records):
            return
        rec = self._records[row]
        if QMessageBox.question(self, "Remover do histórico", f"Remover este registro de {hr.KINDS[rec.kind]}?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        with Session() as s:
            hr.delete_record(s, rec.id)
        self._fill_history()
        self.changed.emit("Registro removido.")


class HrPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.status = "active"
        self.items: list[hr.EmployeeView] = []

        self.group = QButtonGroup(self, exclusive=True)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        for i, (k, label) in enumerate(STATUS.items()):
            b = QPushButton(label, checkable=True, checked=(k == "active"))
            b.setProperty("variant", "pill")
            b.setProperty("key", k)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            bar.addWidget(b)
        self.staff = QComboBox()
        self.staff.addItem("Todas as categorias", None)
        for k, label in hr.STAFF.items():
            self.staff.addItem(label, k)
        self.search = QLineEdit(placeholderText="Buscar funcionário…", clearButtonEnabled=True)
        self.search.setMaximumWidth(200)
        bar.addWidget(self.staff)
        bar.addWidget(self.search)
        bar.addStretch(1)
        self.new_btn = button("Novo funcionário", "primary", t, "fa6s.plus", "on_acc")
        bar.addWidget(self.new_btn)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([c for c, _w in COLS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        for i, (_c, w) in enumerate(COLS):
            if w is None:
                hdr.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.Fixed)
                hdr.resizeSection(i, w)
        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.footer = QLabel()
        self.footer.setTextFormat(Qt.RichText)

        self.panel = EmployeePanel(profile, t)
        scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.panel)
        scroll.setFixedWidth(PANEL_W)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addLayout(bar)
        left.addWidget(self.table, 1)
        left.addWidget(self.empty, 1)
        left.addWidget(self.footer)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addLayout(left, 1)
        root.addWidget(scroll)

        self.group.idClicked.connect(self._filter)
        self.staff.currentIndexChanged.connect(lambda _i: self.refresh())
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.table.currentCellChanged.connect(lambda r, *_a: self._selected(r))
        self.new_btn.clicked.connect(self.new_employee)
        self.panel.changed.connect(self._changed)

    def _filter(self, i: int):
        self.status = self.group.button(i).property("key")
        self.refresh()

    def refresh(self, select_id: int | None = None):
        if select_id is None and self.panel.contact_id is not None:
            select_id = self.panel.contact_id
        cur = self.profile.currency
        with Session() as s:
            self.items, summ = hr.list_employees(s, self.profile.id, self.search.text(), self.staff.currentData(),
                                                 None if self.status == "all" else self.status)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        sel = -1
        for r, e in enumerate(self.items):
            cells = [e.name + ("" if e.active else "  (desligado)"), e.job_title, e.employment_type or
                     hr.STAFF[e.staff_category], f"{e.admission_date:%d/%m/%Y}" if e.admission_date else "",
                     money.fmt(e.salary, cur), money.fmt(e.benefits, cur), money.fmt(e.total, cur)]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c >= 3:
                    it.setFont(theme.mono_font())
                if c >= 4:
                    it.setTextAlignment(R)
                self.table.setItem(r, c, it)
            if e.contact_id == select_id:
                sel = r
        if sel >= 0:
            self.table.selectRow(sel)
        self.table.blockSignals(False)
        has = bool(self.items)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        self.empty.setText("Nenhum funcionário aqui.\nUse \"Novo funcionário\" ou marque \"Trabalha para mim\" no "
                           "cadastro do contato." if self.status == "active" and not self.search.text() else
                           "Nada encontrado.")
        self.footer.setText(f"{summ.count} funcionário(s), {summ.active} ativo(s) · Salários "
                            f"{money.fmt(summ.salaries, cur)} · Benefícios {money.fmt(summ.benefits, cur)} · "
                            f"<b>Folha do mês {money.fmt(summ.payroll, cur)}</b>")
        self.panel.open(self.items[sel] if sel >= 0 else None)

    def _selected(self, row: int):
        if 0 <= row < len(self.items):
            self.panel.open(self.items[row])

    def _changed(self, msg: str):
        self.message.emit(msg)
        self.refresh()

    def new_employee(self):
        name, ok = QInputDialog.getText(self, "Novo funcionário", "Nome (pode ser um contato que já existe):")
        if not ok:
            return
        try:
            with Session() as s:
                cid = hr.add_employee(s, self.profile.id, name)
        except ValueError as e:
            QMessageBox.warning(self, "Novo funcionário", str(e))
            return
        self.message.emit(f"\"{name.strip()}\" está no RH. Preencha o perfil ao lado.")
        self.group.button(0).setChecked(True)
        self.status = "active"
        self.refresh(select_id=cid)

    def apply_theme(self, t: dict):
        self.t = self.panel.t = t
