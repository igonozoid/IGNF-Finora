"""Lixeira: lançamentos excluídos, com quem excluiu e quando. Selecione e restaure."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import trash
from finora.ui import theme
from finora.ui.widgets import button, help_icon

COLUMNS = [("EXCLUÍDO EM", 112), ("POR", 110), ("VENC.", 76), ("DESCRIÇÃO", None), ("CONTA", 130), ("VALOR", 120)]


class TrashDialog(QDialog):
    def __init__(self, parent, entity_id: int, t: dict):
        super().__init__(parent)
        self.entity_id, self.t = entity_id, t
        self.restored = 0
        self.setObjectName("wizard")
        self.setWindowTitle("Lixeira")
        self.resize(860, 480)
        self.setMinimumSize(600, 340)

        top = QHBoxLayout()
        title = QLabel("Lixeira", objectName="sectionTitle")
        top.addWidget(title)
        top.addWidget(help_icon("Lançamentos excluídos ficam guardados aqui, sem prazo, e não entram em saldos nem\n"
                                "relatórios. Restaurar devolve o lançamento como estava. Lançamentos de um período\n"
                                "fechado só podem ser restaurados depois de reabrir o período.", t))
        top.addStretch(1)
        self.search = QLineEdit(placeholderText="Procurar…", clearButtonEnabled=True)
        self.search.setMaximumWidth(220)
        top.addWidget(self.search)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        for i, (_t, w) in enumerate(COLUMNS):
            if w is None:
                hdr.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.Fixed)
                hdr.resizeSection(i, w)
        self.table.horizontalHeaderItem(len(COLUMNS) - 1).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.empty = QLabel("A lixeira está vazia.", alignment=Qt.AlignCenter)
        self.empty.setProperty("role", "muted")

        btns = QHBoxLayout()
        self.info = QLabel()
        self.info.setProperty("role", "muted")
        btns.addWidget(self.info, 1)
        close = button("Fechar", "secondary")
        self.restore_btn = button("Restaurar", "primary", t, "fa6s.rotate-left", "on_acc")
        btns.addWidget(close)
        btns.addWidget(self.restore_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.empty, 1)
        lay.addLayout(btns)

        self.search.textChanged.connect(lambda _t: self.refresh())
        self.table.itemSelectionChanged.connect(self._selection)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.restore_selected())
        close.clicked.connect(self.accept)
        self.restore_btn.clicked.connect(self.restore_selected)
        self.refresh()

    def refresh(self):
        with Session() as s:
            self.items = trash.list_trash(s, self.entity_id, self.search.text())
        self.table.setRowCount(len(self.items))
        mono = theme.mono_font()
        for r, it in enumerate(self.items):
            cells = [it.deleted_at.strftime("%d/%m/%y %H:%M"), it.deleted_by, it.due_date.strftime("%d/%m/%y"),
                     it.description, it.account, money.fmt(it.amount, it.currency)]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == len(cells) - 1:
                    item.setFont(mono)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.setVisible(bool(self.items))
        self.empty.setVisible(not self.items)
        self.empty.setText("Nada encontrado." if self.search.text().strip() else "A lixeira está vazia.")
        self._selection()

    def _selected_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.items[r].id for r in rows]

    def _selection(self):
        n = len(self._selected_ids())
        self.restore_btn.setEnabled(n > 0)
        self.restore_btn.setText(f"Restaurar {n}" if n > 1 else "Restaurar")
        total = len(self.items)
        self.info.setText(f"{total} {'lançamento' if total == 1 else 'lançamentos'} na lixeira" if total else "")

    def restore_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        try:
            with Session() as s:
                n = trash.restore(s, ids)
        except ValueError as e:              # período fechado, sem permissão…
            QMessageBox.warning(self, "Restaurar", str(e))
            return
        self.restored += n
        self.refresh()
