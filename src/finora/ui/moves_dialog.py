"""Aplicação, resgate e saque lançados como receita/despesa (decisão D2): conferir e converter em movimentação."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import moves
from finora.ui import theme
from finora.ui.widgets import button, help_icon, set_tone

COL_ON, COL_DAY, COL_KIND, COL_FROM, COL_TO, COL_AMOUNT, COL_DESC = range(7)


class MovesDialog(QDialog):
    def __init__(self, parent, entity_id: int, currency: str, t: dict):
        super().__init__(parent)
        self.entity_id, self.currency, self.t = entity_id, currency, t
        self.rows: list[moves.Move] = []
        self.outcome = ""
        self.setObjectName("wizard")
        self.setWindowTitle("Aplicações, resgates e saques")
        self.resize(900, 540)
        self.setMinimumSize(640, 380)

        intro = QLabel("No MCC, dinheiro que só mudou de conta (aplicação, resgate, saque, depósito) era lançado "
                       "como despesa numa conta e receita na outra. No Finora isso é movimentação: não entra na DRE "
                       "e o saldo das contas não muda.", wordWrap=True)
        intro.setProperty("role", "muted")
        self.words = QLineEdit(moves.WORDS)
        self.search_btn = button("Procurar", "secondary", t, "fa6s.magnifying-glass", "fg")
        head = QHBoxLayout()
        head.addWidget(QLabel("Categorias com"))
        head.addWidget(self.words, 1)
        head.addWidget(help_icon("Palavras do nome da categoria (o \"item\" do MCC), separadas por vírgula.\n"
                                 "Despesa numa conta + receita de mesmo valor em outra (até 3 dias) = "
                                 "transferência.\nSó um lado: despesa vira retirada e receita vira depósito "
                                 "(venha desmarcado: confira).", t))
        head.addWidget(self.search_btn)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "DATA", "VIRA", "SAI DE", "ENTRA EM", "VALOR", "DESCRIÇÃO"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H + 4)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        for col in (COL_ON, COL_DAY, COL_KIND, COL_FROM, COL_TO, COL_AMOUNT):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)

        self.error = QLabel(wordWrap=True)
        set_tone(self.error, "neg")
        foot = QHBoxLayout()
        self.count = QLabel()
        self.count.setProperty("role", "muted")
        foot.addWidget(self.count)
        foot.addStretch(1)
        close = button("Fechar", "secondary")
        self.apply_btn = button("Converter", "primary")
        foot.addWidget(close)
        foot.addWidget(self.apply_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(intro)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.error)
        lay.addLayout(foot)
        close.clicked.connect(self.reject)
        self.apply_btn.clicked.connect(self.apply)
        self.search_btn.clicked.connect(self.load)
        self.words.returnPressed.connect(self.load)
        self.load()

    def load(self):
        self.error.clear()
        with Session() as s:
            self.rows = moves.find(s, self.entity_id, self.words.text())
        self.table.setRowCount(len(self.rows))
        mono = theme.mono_font()
        for i, m in enumerate(self.rows):
            chk = QCheckBox(checked=m.kind == "transfer")          # par: certo; avulso: o usuário confere
            chk.toggled.connect(self._update)
            self.table.setCellWidget(i, COL_ON, chk)
            cells = {COL_DAY: f"{m.day:%d/%m/%Y}", COL_KIND: m.kind_label, COL_FROM: m.from_account or "—",
                     COL_TO: m.to_account or "—", COL_AMOUNT: money.fmt(m.amount, self.currency),
                     COL_DESC: m.description}
            for col, text in cells.items():
                it = QTableWidgetItem(text)
                if col in (COL_DAY, COL_AMOUNT):
                    it.setFont(mono)
                if col == COL_AMOUNT:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, col, it)
        self._update()

    def chosen(self) -> list[moves.Move]:
        return [m for i, m in enumerate(self.rows) if self.table.cellWidget(i, COL_ON).isChecked()]

    def _update(self):
        n = len(self.chosen())
        self.count.setText(f"{n} de {len(self.rows)} marcada(s)" if self.rows else
                           "Nada encontrado com essas palavras.")
        self.apply_btn.setEnabled(n > 0)

    def apply(self):
        try:
            with Session() as s:
                done = moves.convert(s, self.entity_id, self.chosen())
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.outcome = (f"Convertido: {done['transfer']} transferência(s), {done['withdrawal']} retirada(s) e "
                        f"{done['deposit']} depósito(s).")
        self.accept()
