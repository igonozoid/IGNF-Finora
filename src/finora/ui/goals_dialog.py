"""Metas e objetivos: lista à esquerda, formulário à direita (Dashboard › Metas › Gerenciar)."""
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, goals
from finora.ui import theme
from finora.ui.widgets import button, field_label, help_icon


def describe(g: goals.GoalView, currency: str) -> str:
    """'R$ 1.500,00 de R$ 6.000,00 · faltam R$ 4.500,00 · guardar R$ 750,00/mês até abr/2027'."""
    text = f"{money.fmt(g.current, currency)} de {money.fmt(g.target, currency)}"
    if g.done:
        return text + " · meta atingida! 🎉"
    text += f" · faltam {money.fmt(g.missing, currency)}"
    monthly = g.monthly()
    if monthly is not None and g.due_date:
        text += f" · guardar {money.fmt(monthly, currency)}/mês até {g.due_date:%m/%Y}"
    return text


def ask_saving(parent, g: goals.GoalView, currency: str) -> Decimal | None:
    text, ok = QInputDialog.getText(parent, "Guardei mais", f"Quanto você guardou para “{g.name}”?\n"
                                    "(Use um valor negativo se tirou dinheiro.)")
    if not ok or not text.strip():
        return None
    try:
        return money.parse(text)
    except ValueError:
        QMessageBox.warning(parent, "Guardei mais", "Valor inválido.")
        return None


class GoalsDialog(QDialog):
    def __init__(self, parent, entity_id: int, currency: str, t: dict, select_id: int | None = None):
        super().__init__(parent)
        self.entity_id, self.currency, self.t = entity_id, currency, t
        self.current: goals.GoalView | None = None
        self.changed = False
        self.setObjectName("wizard")
        self.setWindowTitle("Metas e objetivos")
        self.resize(900, 500)
        self.setMinimumSize(700, 400)

        top = QHBoxLayout()
        top.addWidget(QLabel("Metas e objetivos", objectName="sectionTitle"))
        top.addWidget(help_icon("Reserva de emergência, viagem, carro novo… Diga quanto quer juntar e, se quiser,\n"
                                "até quando: o Finora mostra quanto falta e quanto guardar por mês.\n"
                                "O progresso pode ser o saldo de uma conta (ex.: a poupança da reserva) ou um\n"
                                "valor que você vai somando em \"Guardei mais\".", t))
        top.addStretch(1)
        self.show_done = QCheckBox("Mostrar arquivadas")
        top.addWidget(self.show_done)
        self.new_btn = button("Nova meta", "secondary", t, "fa6s.plus", "fg")
        top.addWidget(self.new_btn)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["META", "PROGRESSO", "ATÉ"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 90), (2, 80)):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
            hdr.resizeSection(c, w)
        self.empty = QLabel("Nenhuma meta ainda. Clique em Nova meta.", alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")

        panel = QFrame(objectName="card")
        panel.setFixedWidth(330)
        form = QGridLayout(panel)
        form.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        form.setVerticalSpacing(3)
        self.panel_title = QLabel(objectName="sectionTitle")
        self.name = QLineEdit(maxLength=80, placeholderText="Ex.: Reserva de emergência")
        self.target = QLineEdit(placeholderText="0,00")
        self.target.setFont(theme.mono_font())
        self.target.setAlignment(Qt.AlignRight)
        self.has_due = QCheckBox("Tem data para chegar lá")
        self.due = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.source = QComboBox()
        self.saved = QLineEdit(placeholderText="0,00")
        self.saved.setFont(theme.mono_font())
        self.saved.setAlignment(Qt.AlignRight)
        self.saved_lbl = field_label("Já guardado", t)
        self.active = QCheckBox("Meta ativa (aparece no Dashboard)", checked=True)
        self.progress = QLabel(wordWrap=True)
        self.progress.setProperty("role", "muted")
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        r = 0
        form.addWidget(self.panel_title, r, 0)
        for label, w in (("Nome", self.name), ("Quanto quer juntar", self.target)):
            form.addWidget(field_label(label, t), r + 1, 0)
            form.addWidget(w, r + 2, 0)
            r += 2
        form.addWidget(self.has_due, r + 1, 0)
        form.addWidget(self.due, r + 2, 0)
        form.addWidget(field_label("Acompanhar pelo", t, "Saldo de uma conta: o progresso muda sozinho com os\n"
                                                         "lançamentos dela. Valor informado: você soma em\n"
                                                         "\"Guardei mais\"."), r + 3, 0)
        form.addWidget(self.source, r + 4, 0)
        form.addWidget(self.saved_lbl, r + 5, 0)
        form.addWidget(self.saved, r + 6, 0)
        form.addWidget(self.active, r + 7, 0)
        form.addWidget(self.progress, r + 8, 0)
        form.addWidget(self.error, r + 9, 0)
        form.setRowStretch(r + 10, 1)
        pb = QHBoxLayout()
        self.delete_btn = button("Excluir", "link", t, "fa6s.trash-can")
        self.add_btn = button("Guardei mais", "secondary", t, "fa6s.piggy-bank", "fg")
        self.save_btn = button("Salvar", "primary", t, "fa6s.check", "on_acc")
        pb.addWidget(self.delete_btn)
        pb.addStretch(1)
        pb.addWidget(self.add_btn)
        pb.addWidget(self.save_btn)
        form.addLayout(pb, r + 11, 0)

        body = QHBoxLayout()
        body.setSpacing(theme.SP_L)
        left = QVBoxLayout()
        left.addWidget(self.table, 1)
        left.addWidget(self.empty, 1)
        body.addLayout(left, 1)
        body.addWidget(panel)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = button("Fechar", "secondary")
        bottom.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(top)
        lay.addLayout(body, 1)
        lay.addLayout(bottom)

        self.new_btn.clicked.connect(self.new_goal)
        self.save_btn.clicked.connect(self.save)
        self.delete_btn.clicked.connect(self.delete)
        self.add_btn.clicked.connect(self.add_saving)
        close.clicked.connect(self.accept)
        self.has_due.toggled.connect(self.due.setEnabled)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.show_done.toggled.connect(lambda _on: self.refresh())
        self.table.itemSelectionChanged.connect(self._picked)
        with Session() as s:
            accs = [a for a in accounts.list_accounts(s, entity_id) if a.kind != "card"]
        self.source.addItem("Valor que eu informo", None)
        for a in accs:
            self.source.addItem(f"Saldo da conta {a.name}", a.id)
        self.refresh(select_id)
        if self.current is None:
            if self.items:
                self.table.selectRow(0)
            else:
                self.new_goal()

    def refresh(self, select_id: int | None = None):
        with Session() as s:
            self.items = goals.list_goals(s, self.entity_id, include_inactive=self.show_done.isChecked())
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        row_sel = None
        for r, g in enumerate(self.items):
            cells = [g.name, f"{g.pct}%", g.due_date.strftime("%m/%Y") if g.due_date else "—"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if not g.is_active:
                    item.setForeground(self.palette().placeholderText())
                self.table.setItem(r, c, item)
            if g.id == select_id:
                row_sel = r
        self.table.blockSignals(False)
        self.table.setVisible(bool(self.items))
        self.empty.setVisible(not self.items)
        if row_sel is not None:
            self.table.selectRow(row_sel)

    def _source_changed(self):
        manual = self.source.currentData() is None
        self.saved_lbl.setVisible(manual)
        self.saved.setVisible(manual)
        self.add_btn.setVisible(manual and self.current is not None)

    def new_goal(self):
        self.current = None
        self.table.clearSelection()
        self.panel_title.setText("Nova meta")
        self.name.clear()
        self.target.clear()
        self.has_due.setChecked(False)
        self.due.setDate(QDate.currentDate().addYears(1))
        self.due.setEnabled(False)
        self.source.setCurrentIndex(0)
        self.saved.clear()
        self.active.setChecked(True)
        self.progress.clear()
        self.delete_btn.hide()
        self.error.hide()
        self._source_changed()
        self.name.setFocus()

    def _picked(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return
        g = self.items[min(rows)]
        self.current = g
        self.panel_title.setText("Editar meta")
        self.name.setText(g.name)
        self.target.setText(money.fmt(g.target, self.currency).split(" ", 1)[-1])
        self.has_due.setChecked(g.due_date is not None)
        self.due.setEnabled(g.due_date is not None)
        if g.due_date:
            self.due.setDate(QDate(g.due_date.year, g.due_date.month, g.due_date.day))
        self.source.setCurrentIndex(max(0, self.source.findData(g.account_id)))
        self.saved.setText(money.fmt(g.saved, self.currency).split(" ", 1)[-1])
        self.active.setChecked(g.is_active)
        self.progress.setText(describe(g, self.currency))
        self.delete_btn.show()
        self.error.hide()
        self._source_changed()

    def _values(self) -> dict:
        try:
            target = money.parse(self.target.text())
            saved = money.parse(self.saved.text()) if self.source.currentData() is None else None
        except ValueError:
            raise ValueError("Valor inválido.")
        return dict(name=self.name.text(), target=target,
                    due_date=self.due.date().toPython() if self.has_due.isChecked() else None,
                    account_id=self.source.currentData(), saved=saved)

    def save(self):
        try:
            data = self._values()
            with Session() as s:
                if self.current is None:
                    gid = goals.create(s, self.entity_id, **{**data, "saved": data["saved"] or Decimal(0)})
                else:
                    gid = self.current.id
                    goals.update(s, gid, is_active=self.active.isChecked(), **data)
        except ValueError as e:
            self.error.setText(str(e))
            self.error.show()
            return
        self.changed = True
        self.refresh(gid)
        self._picked()

    def add_saving(self):
        if self.current is None:
            return
        amount = ask_saving(self, self.current, self.currency)
        if amount is None:
            return
        try:
            with Session() as s:
                goals.add_saving(s, self.current.id, amount)
        except ValueError as e:
            QMessageBox.warning(self, "Guardei mais", str(e))
            return
        self.changed = True
        self.refresh(self.current.id)
        self._picked()

    def delete(self):
        if self.current is None:
            return
        if QMessageBox.question(self, "Excluir meta", f"Excluir a meta “{self.current.name}”?\n"
                                "(Para só tirar do Dashboard, desmarque \"Meta ativa\".)",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        with Session() as s:
            goals.delete(s, self.current.id)
        self.changed = True
        self.refresh()
        self.new_goal()

