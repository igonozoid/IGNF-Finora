"""Tela Produção (módulo "production"): lotes do período e resumo do que foi produzido, com custo por unidade."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import export, production, reports, stock
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, help_icon

R = Qt.AlignRight | Qt.AlignVCenter
L = Qt.AlignLeft | Qt.AlignVCenter
VIEWS = {"batches": "Lotes", "item": "Por produto"}
BATCH_COLS = [("Nº", 50, True), ("DATA", 80, False), ("LOTE", None, False), ("INSUMOS", None, False),
              ("PRODUTOS", None, False), ("SITUAÇÃO", 110, False), ("CUSTO", 120, True), ("CUSTO/UN.", 110, True),
              ("RENDIMENTO", 130, True)]
SUM_COLS = [("PRODUTO", None, False), ("LOTES", 70, True), ("QUANTIDADE", 130, True), ("CUSTO", 130, True),
            ("CUSTO MÉDIO/UN.", 130, True)]
PERIODS = {**reports.LIST_PERIODS, "all": "Todo o período"}


class ProductionPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.rows: list = []
        self.view = "batches"

        self.group = QButtonGroup(self, exclusive=True)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        for i, (k, label) in enumerate(VIEWS.items()):
            b = QPushButton(label, checkable=True, checked=(k == "batches"))
            b.setProperty("variant", "pill")
            b.setProperty("view", k)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            bar.addWidget(b)
        bar.addSpacing(theme.SP_M)
        self.period = QComboBox()
        for k, label in PERIODS.items():
            self.period.addItem(label, k)
        self.status = QComboBox()
        self.status.addItem("Todas as situações", None)
        for k, label in production.STATUS.items():
            self.status.addItem(label, k)
        self.search = QLineEdit(placeholderText="Lote ou nº…", clearButtonEnabled=True)
        self.search.setMaximumWidth(180)
        for w in (self.period, self.status, self.search):
            bar.addWidget(w)
        bar.addWidget(help_icon("Lote em andamento não mexe no estoque. Ao concluir, os insumos saem pelo custo médio\n"
                                "e os produtos entram com o custo do lote (insumos + outros custos) dividido pela\n"
                                "quantidade. Esse custo é o que aparece na margem das Vendas.", t))
        bar.addStretch(1)
        more = button("Imprimir/Exportar", "secondary", t, "fa6s.print", "fg")
        menu = QMenu(more)
        menu.addAction("Imprimir…", self._print)
        menu.addAction("Excel…", lambda: self._export("xlsx"))
        more.setMenu(menu)
        self.new_btn = button("Novo lote", "primary", t, "fa6s.plus", "on_acc")
        bar.addWidget(more)
        bar.addWidget(self.new_btn)

        self.table = QTableWidget(0, 1)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.footer = QLabel()
        self.footer.setTextFormat(Qt.RichText)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(10)
        root.addLayout(bar)
        root.addWidget(self.table, 1)
        root.addWidget(self.empty, 1)
        root.addWidget(self.footer)

        self.group.idClicked.connect(self._view_changed)
        self.period.currentIndexChanged.connect(lambda _i: self.refresh())
        self.status.currentIndexChanged.connect(lambda _i: self.refresh())
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_batch(r))
        self.new_btn.clicked.connect(lambda: self.open_batch(None))

    def _view_changed(self, i: int):
        self.view = self.group.button(i).property("view")
        self.status.setVisible(self.view == "batches")
        self.search.setVisible(self.view == "batches")
        self.refresh()

    def _columns(self, cols):
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels([c[0] for c in cols])
        hdr = self.table.horizontalHeader()
        for i, (_t, w, right) in enumerate(cols):
            if w is None:
                hdr.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.Fixed)
                hdr.resizeSection(i, w)
            self.table.horizontalHeaderItem(i).setTextAlignment(R if right else L)

    def _range(self):
        key = self.period.currentData()
        return (None, None) if key == "all" else reports.period_range(key)

    def refresh(self):
        first, last = self._range()
        cur = self.profile.currency
        with Session() as s:
            if self.view == "batches":
                self.rows = production.list_productions(s, self.profile.id, first, last, self.status.currentData(),
                                                        self.search.text())
            else:
                self.rows = production.summary(s, self.profile.id, first or date(2000, 1, 1),
                                               last or date(2100, 1, 1))
        cols = BATCH_COLS if self.view == "batches" else SUM_COLS
        self._columns(cols)
        self.table.setRowCount(len(self.rows))
        mono = theme.mono_font()
        for r, row in enumerate(self.rows):
            if self.view == "batches":
                done = row.status == "done"
                cells = [str(row.number), row.day.strftime("%d/%m/%y"), row.name, row.inputs, row.outputs,
                         row.status_label, money.fmt(row.total_cost, cur) if done else "",
                         money.fmt(row.unit_cost, cur) if done and row.unit_cost is not None else "",
                         row.yield_text]
                tone = None if done else "mut"
            else:
                cells = [row.name, str(row.batches), stock.fmt_qty(row.quantity, row.unit), money.fmt(row.cost, cur),
                         money.fmt(row.unit_cost, cur) if row.unit_cost is not None else "—"]
                tone = None
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if cols[c][2]:
                    item.setFont(mono)
                    item.setTextAlignment(R)
                if tone:
                    item.setForeground(QBrush(QColor(self.t[tone])))
                if self.view == "batches":
                    item.setToolTip("Dois cliques para abrir o lote")
                self.table.setItem(r, c, item)
        self.table.setVisible(bool(self.rows))
        self.empty.setVisible(not self.rows)
        self.empty.setText("Nenhum lote nesse período. Clique em Novo lote." if self.view == "batches"
                           else "Nenhum lote concluído nesse período.")
        self._footer()

    def _footer(self):
        cur = self.profile.currency
        if self.view == "batches":
            done = [r for r in self.rows if r.status == "done"]
            cost = sum((r.total_cost for r in done), Decimal(0))
            open_ = len(self.rows) - len(done)
            self.footer.setText(f"{len(done)} {'lote concluído' if len(done) == 1 else 'lotes concluídos'} "
                                f"&nbsp;·&nbsp; custo <b>{money.fmt(cost, cur)}</b>"
                                + (f" &nbsp;·&nbsp; {open_} em andamento" if open_ else ""))
        else:
            cost = sum((r.cost for r in self.rows), Decimal(0))
            self.footer.setText(f"Custo total produzido <b>{money.fmt(cost, cur)}</b>")

    def open_batch(self, row: int | None):
        from finora.ui.production_dialog import ProductionDialog
        if row is not None and (self.view != "batches" or not (0 <= row < len(self.rows))):
            return
        with Session() as s:
            if not stock.list_items(s, self.profile.id):
                self.message.emit("Cadastre os insumos e produtos em Estoque antes de produzir.")
                return
        dlg = ProductionDialog(self, self.profile.id, self.profile.currency, self.t,
                               self.rows[row].id if row is not None else None)
        if dlg.exec() and dlg.done_text:
            self.message.emit(dlg.done_text)
        self.refresh()

    def export_sheet(self) -> export.Sheet:
        cur = self.profile.currency
        if self.view == "batches":
            sheet = export.Sheet("Lotes de produção", self.period.currentText(),
                                 ["Nº", "Data", "Lote", "Insumos", "Produtos", "Situação", "Custo", "Custo/un.",
                                  "Rendimento"], currency=cur)
            for r in self.rows:
                done = r.status == "done"
                sheet.add([str(r.number), r.day, r.name, r.inputs, r.outputs, r.status_label,
                           r.total_cost if done else None, r.unit_cost if done else None, r.yield_text])
        else:
            sheet = export.Sheet("Produção por produto", self.period.currentText(),
                                 ["Produto", "Lotes", "Quantidade", "Custo", "Custo médio/un."], currency=cur)
            for r in self.rows:
                sheet.add([r.name, str(r.batches), stock.fmt_qty(r.quantity, r.unit), r.cost, r.unit_cost])
        import re
        sheet.footer = " ".join(re.sub(r"<[^>]+>", "", self.footer.text()).replace("&nbsp;", " ").split())
        return sheet

    def _print(self):
        from finora.ui import printing
        printing.open_print(self, self.export_sheet(), self.t)

    def _export(self, kind: str):
        from finora.core.licensing import allowed, current_edition
        from finora.ui import exporting
        from finora.ui.widgets import show_upgrade
        if not allowed(current_edition(), "export"):
            show_upgrade(self, "Exportar para Excel e PDF é um recurso da edição Plus.")
            return
        path = exporting.run(self, self.export_sheet(), kind)
        if path:
            self.message.emit(f"Salvo em {path}")

    def apply_theme(self, t: dict):
        self.t = t
        if self.isVisible():
            self.refresh()
