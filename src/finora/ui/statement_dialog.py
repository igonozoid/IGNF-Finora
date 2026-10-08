"""Importar extrato/fatura em planilha: conferir as colunas que o Finora adivinhou, ver a prévia e importar."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from finora.core import money
from finora.services import statement_import as si
from finora.ui import theme
from finora.ui.widgets import button, field_label, help_icon

PREVIEW = 15


class StatementDialog(QDialog):
    def __init__(self, parent, rows: list[list[str]], filename: str, account: str, is_card: bool, currency: str,
                 t: dict):
        super().__init__(parent)
        self.rows, self.currency, self.t = rows, currency, t
        self.parsed: si.Parsed | None = None
        self.setObjectName("wizard")
        self.setWindowTitle(f"Importar planilha — {account}")
        self.resize(860, 560)
        self.setMinimumSize(640, 420)
        width = max(len(r) for r in rows)
        guess = si.guess(rows)
        heads = rows[guess.header_row] if guess.header_row >= 0 else []

        def col_name(c: int) -> str:
            title = heads[c] if c < len(heads) and heads[c] else ""
            letter = chr(ord("A") + c) if c < 26 else str(c + 1)
            return f"{letter} · {title}" if title else f"Coluna {letter}"

        top = QHBoxLayout()
        top.addWidget(QLabel(filename, objectName="sectionTitle"))
        top.addWidget(help_icon("O Finora tentou adivinhar as colunas da planilha do banco. Confira na prévia:\n"
                                "cada linha precisa de data, descrição e valor (saídas negativas).\n"
                                "Se o banco separa em duas colunas, use Entrada e Saída em vez de Valor.\n"
                                "Linhas de saldo e de total são puladas. Importar de novo não duplica.", t))
        top.addStretch(1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP_M)
        grid.setVerticalSpacing(3)
        self.boxes: dict[str, QComboBox] = {}
        fields = (("date_col", "Data"), ("desc_col", "Descrição"), ("amount_col", "Valor"), ("in_col", "Entrada"),
                  ("out_col", "Saída"))
        for i, (key, label) in enumerate(fields):
            box = QComboBox()
            box.addItem("—", -1)
            for c in range(width):
                box.addItem(col_name(c), c)
            box.setCurrentIndex(max(0, box.findData(getattr(guess, key))))
            box.currentIndexChanged.connect(self._update)
            self.boxes[key] = box
            grid.addWidget(field_label(label, t), 0, i)
            grid.addWidget(box, 1, i)
        self.header = QSpinBox(minimum=0, maximum=min(30, len(rows)), value=guess.header_row + 1)
        self.header.setSpecialValueText("Sem títulos")
        self.header.setToolTip("Em que linha estão os títulos das colunas (0 = a planilha não tem títulos)")
        self.header.valueChanged.connect(self._update)
        grid.addWidget(field_label("Títulos na linha", t), 0, len(fields))
        grid.addWidget(self.header, 1, len(fields))
        self.invert = QCheckBox("Fatura de cartão: as compras vêm positivas (virar saídas)")
        self.invert.toggled.connect(self._update)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["DATA", "DESCRIÇÃO", "VALOR"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.resizeSection(0, 90)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.resizeSection(2, 130)
        self.status = QLabel(wordWrap=True)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancelar", "secondary")
        self.ok = button("Importar", "primary", t, "fa6s.file-import", "on_acc")
        btns.addWidget(cancel)
        btns.addWidget(self.ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(top)
        lay.addLayout(grid)
        lay.addWidget(self.invert)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)
        lay.addLayout(btns)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.accept)

        self._update()
        if is_card and self.parsed and sum(1 for ln in self.parsed.lines if ln.amount > 0) > len(self.parsed.lines) / 2:
            self.invert.setChecked(True)          # fatura com compras positivas: o mais comum

    def mapping(self) -> si.Mapping:
        m = si.Mapping(header_row=self.header.value() - 1, invert=self.invert.isChecked())
        for key, box in self.boxes.items():
            setattr(m, key, box.currentData())
        if m.amount_col >= 0:                     # valor único manda; entrada/saída só sem ele
            m.in_col = m.out_col = -1
        return m

    def _update(self):
        try:
            self.parsed = si.parse(self.rows, self.mapping())
        except ValueError as e:
            self.parsed = None
            self.table.setRowCount(0)
            self.status.setProperty("role", "error")
            self.status.setText(str(e))
            self.status.style().polish(self.status)
            self.ok.setEnabled(False)
            return
        lines = self.parsed.lines
        self.table.setRowCount(min(PREVIEW, len(lines)))
        mono = theme.mono_font()
        for r, ln in enumerate(lines[:PREVIEW]):
            for c, text in enumerate((ln.posted.strftime("%d/%m/%Y"), ln.memo, money.fmt(ln.amount, self.currency))):
                item = QTableWidgetItem(text)
                if c == 2:
                    item.setFont(mono)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        out = sum(1 for ln in lines if ln.amount < 0)
        text = (f"{len(lines)} {'movimentação' if len(lines) == 1 else 'movimentações'} "
                f"({len(lines) - out} entradas, {out} saídas), de {min(ln.posted for ln in lines):%d/%m/%Y} "
                f"a {max(ln.posted for ln in lines):%d/%m/%Y}.")
        if self.parsed.skipped:
            text += f" {self.parsed.skipped} {'linha pulada' if self.parsed.skipped == 1 else 'linhas puladas'} " \
                    "(títulos, saldos, totais)."
        if len(lines) > PREVIEW:
            text += f" A prévia mostra as {PREVIEW} primeiras."
        self.status.setProperty("role", "muted")
        self.status.setText(text)
        self.status.style().polish(self.status)
        self.ok.setEnabled(True)
