"""Regras automáticas de categoria: lista à esquerda, formulário à direita (Categorias › Regras automáticas)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.services import categories, contacts, cost_centers, rules
from finora.ui import theme
from finora.ui.widgets import button, field_label, help_icon

HELP = ("Quando a descrição de um lançamento novo (ou o texto do extrato do banco) contém o texto da regra,\n"
        "o Finora já preenche a categoria, o contato e o centro de custo. Não diferencia acentos nem maiúsculas.\n"
        "Se mais de uma regra servir, vale a de texto mais longo. Ex.: “uber” → Transporte; “uber eats” → Alimentação.")


class RulesDialog(QDialog):
    def __init__(self, parent, entity_id: int, t: dict):
        super().__init__(parent)
        self.entity_id, self.t = entity_id, t
        self.current: rules.RuleView | None = None
        self.changed = False
        self.setObjectName("wizard")
        self.setWindowTitle("Regras automáticas")
        self.resize(940, 520)
        self.setMinimumSize(720, 400)

        top = QHBoxLayout()
        top.addWidget(QLabel("Regras automáticas", objectName="sectionTitle"))
        top.addWidget(help_icon(HELP, t))
        top.addStretch(1)
        self.new_btn = button("Nova regra", "secondary", t, "fa6s.plus", "fg")
        top.addWidget(self.new_btn)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["SE CONTÉM", "TIPO", "PREENCHE"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.resizeSection(0, 150)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        hdr.resizeSection(1, 90)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        self.empty = QLabel("Nenhuma regra ainda. Clique em Nova regra.", alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")

        # formulário
        panel = QFrame(objectName="card")
        panel.setFixedWidth(320)
        form = QGridLayout(panel)
        form.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        form.setVerticalSpacing(3)
        self.panel_title = QLabel(objectName="sectionTitle")
        self.text = QLineEdit(maxLength=80, placeholderText="Ex.: uber, ifood, enel")
        self.kind = QComboBox()
        for k, label in rules.KINDS.items():
            self.kind.addItem(label, k)
        self.category = QComboBox()
        self.contact = QComboBox()
        self.cost_center = QComboBox()
        self.description = QLineEdit(maxLength=200, placeholderText="Opcional: troca a descrição")
        self.active = QCheckBox("Regra ativa", checked=True)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        with Session() as s:
            self.can_cc = bool(allowed(current_edition(), "cost_centers")) and bool(
                cost_centers.choices(s, entity_id))
        rows = [("Se a descrição contém", self.text), ("Vale para", self.kind), ("Categoria", self.category),
                ("Contato", self.contact)]
        if self.can_cc:
            rows.append(("Centro de custo", self.cost_center))
        rows.append(("Descrição do lançamento", self.description))
        form.addWidget(self.panel_title, 0, 0)
        r = 1
        for label, w in rows:
            form.addWidget(field_label(label, t), r, 0)
            form.addWidget(w, r + 1, 0)
            r += 2
        form.addWidget(self.active, r, 0)
        form.addWidget(self.error, r + 1, 0)
        form.setRowStretch(r + 2, 1)
        pb = QHBoxLayout()
        self.delete_btn = button("Excluir", "link", t, "fa6s.trash-can")
        self.save_btn = button("Salvar", "primary", t, "fa6s.check", "on_acc")
        pb.addWidget(self.delete_btn)
        pb.addStretch(1)
        pb.addWidget(self.save_btn)
        form.addLayout(pb, r + 3, 0)

        body = QHBoxLayout()
        body.setSpacing(theme.SP_L)
        left = QVBoxLayout()
        left.addWidget(self.table, 1)
        left.addWidget(self.empty, 1)
        body.addLayout(left, 1)
        body.addWidget(panel)

        bottom = QHBoxLayout()
        self.apply_btn = button("Aplicar aos lançamentos sem categoria", "secondary", t, "fa6s.wand-magic-sparkles",
                                "fg")
        self.apply_btn.setToolTip("Usa as regras para preencher os lançamentos que ainda estão sem categoria.\n"
                                  "Não mexe nos que já têm categoria nem em período fechado.")
        close = button("Fechar", "secondary")
        bottom.addWidget(self.apply_btn)
        bottom.addStretch(1)
        bottom.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(top)
        lay.addLayout(body, 1)
        lay.addLayout(bottom)

        self.new_btn.clicked.connect(self.new_rule)
        self.save_btn.clicked.connect(self.save)
        self.delete_btn.clicked.connect(self.delete)
        self.apply_btn.clicked.connect(self.apply_existing)
        close.clicked.connect(self.accept)
        self.kind.currentIndexChanged.connect(lambda _i: self._load_categories(self.category.currentData()))
        self.table.itemSelectionChanged.connect(self._picked)
        self._load_lists()
        self.refresh()
        if self.items:
            self.table.selectRow(0)
        else:
            self.new_rule()

    # ----- listas -----
    def _load_lists(self):
        with Session() as s:
            people = [(c.id, c.name) for c in contacts.list_contacts(s, self.entity_id)]
            ccs = cost_centers.choices(s, self.entity_id) if self.can_cc else []
        self.contact.clear()
        self.contact.addItem("Não mudar", None)
        for cid, name in people:
            self.contact.addItem(name, cid)
        self.cost_center.clear()
        self.cost_center.addItem("Não mudar", None)
        for cid, name in ccs:
            self.cost_center.addItem(name, cid)
        self._load_categories(None)

    def _load_categories(self, keep: int | None):
        kind = self.kind.currentData()
        with Session() as s:
            items = []
            for k in (("expense", "income") if not kind else (kind,)):
                prefix = "" if kind else ("Despesa · " if k == "expense" else "Receita · ")
                items += [(cid, prefix + label) for cid, label in categories.choices(s, self.entity_id, k)]
        self.category.clear()
        self.category.addItem("Não mudar", None)
        for cid, label in items:
            self.category.addItem(label, cid)
        self.category.setCurrentIndex(max(0, self.category.findData(keep)) if keep else 0)

    def refresh(self, select_id: int | None = None):
        with Session() as s:
            self.items = rules.list_rules(s, self.entity_id)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            cells = [it.text, {"": "Ambos", "expense": "Despesa", "income": "Receita"}[it.kind], it.summary]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if not it.is_active:
                    item.setForeground(self.palette().placeholderText())
                    item.setToolTip("Regra inativa")
                self.table.setItem(r, c, item)
            if it.id == select_id:
                self.table.selectRow(r)
        self.table.blockSignals(False)
        self.table.setVisible(bool(self.items))
        self.empty.setVisible(not self.items)

    # ----- formulário -----
    def new_rule(self):
        self.current = None
        self.table.clearSelection()
        self.panel_title.setText("Nova regra")
        self.text.clear()
        self.kind.setCurrentIndex(self.kind.findData("expense"))
        self._load_categories(None)
        for box in (self.contact, self.cost_center):
            box.setCurrentIndex(0)
        self.description.clear()
        self.active.setChecked(True)
        self.delete_btn.hide()
        self.error.hide()
        self.text.setFocus()

    def _picked(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return
        it = self.items[min(rows)]
        self.current = it
        self.panel_title.setText("Editar regra")
        self.text.setText(it.text)
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(self.kind.findData(it.kind))
        self.kind.blockSignals(False)
        self._load_categories(it.category_id)
        self.contact.setCurrentIndex(max(0, self.contact.findData(it.contact_id)))
        self.cost_center.setCurrentIndex(max(0, self.cost_center.findData(it.cost_center_id)))
        self.description.setText(it.description)
        self.active.setChecked(it.is_active)
        self.delete_btn.show()
        self.error.hide()

    def save(self):
        data = dict(text=self.text.text(), kind=self.kind.currentData(), category_id=self.category.currentData(),
                    contact_id=self.contact.currentData(),
                    cost_center_id=self.cost_center.currentData() if self.can_cc else None,
                    description=self.description.text())
        try:
            with Session() as s:
                if self.current is None:
                    rid = rules.create(s, self.entity_id, **data)
                else:
                    rid = self.current.id
                    rules.update(s, rid, is_active=self.active.isChecked(), **data)
        except ValueError as e:
            self.error.setText(str(e))
            self.error.show()
            return
        self.changed = True
        self.refresh(select_id=rid)
        self._picked()

    def delete(self):
        if self.current is None:
            return
        if QMessageBox.question(self, "Excluir regra", f"Excluir a regra “{self.current.text}”?\n"
                                "Os lançamentos que ela já preencheu continuam como estão.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        with Session() as s:
            rules.delete(s, self.current.id)
        self.changed = True
        self.refresh()
        self.new_rule()

    def apply_existing(self):
        try:
            with Session() as s:
                n = rules.apply_to_existing(s, self.entity_id)
        except ValueError as e:
            QMessageBox.warning(self, "Aplicar regras", str(e))
            return
        self.changed = self.changed or n > 0
        QMessageBox.information(self, "Aplicar regras",
                                "Nenhum lançamento sem categoria combina com as regras." if not n else
                                f"{n} {'lançamento foi preenchido' if n == 1 else 'lançamentos foram preenchidos'}.")
