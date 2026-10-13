"""Tela Vendas (módulo "sales"): pedidos do período e resumos por produto e por cliente, com margem."""
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import export, reports, sales, stock
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, help_icon

R = Qt.AlignRight | Qt.AlignVCenter
L = Qt.AlignLeft | Qt.AlignVCenter
VIEWS = {"orders": "Pedidos", "item": "Por produto", "client": "Por cliente"}
ORDER_COLS = [("Nº", 50, True), ("DATA", 80, False), ("CLIENTE", None, False), ("TIPO", 100, False),
              ("SITUAÇÃO", 100, False), ("ITENS", 60, True), ("TOTAL", 120, True), ("RECEBIDO", 120, True)]
SUM_COLS = [("NOME", None, False), ("QUANTIDADE", 120, True), ("RECEITA", 120, True), ("CUSTO", 120, True),
            ("MARGEM", 120, True), ("MARGEM %", 90, True)]
PERIODS = {**reports.LIST_PERIODS, "all": "Todo o período"}


class SalesPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.rows: list = []
        self.view = "orders"

        self.group = QButtonGroup(self, exclusive=True)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        for i, (k, label) in enumerate(VIEWS.items()):
            b = QPushButton(label, checkable=True, checked=(k == "orders"))
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
        for k, label in sales.STATUS.items():
            self.status.addItem(label + "s", k)
        self.search = QLineEdit(placeholderText="Cliente ou nº…", clearButtonEnabled=True)
        self.search.setMaximumWidth(180)
        for w in (self.period, self.status, self.search):
            bar.addWidget(w)
        bar.addWidget(help_icon("Pedido nasce como orçamento (não mexe em nada). Ao confirmar, baixa o estoque e a\n"
                                "venda vira Contas a receber (à vista ou parcelada). Doação e bonificação só baixam\n"
                                "o estoque. Margem = preço − custo médio do item no dia da venda.", t))
        bar.addStretch(1)
        more = button("Imprimir/Exportar", "secondary", t, "fa6s.print", "fg")
        menu = QMenu(more)
        menu.addAction("Imprimir…", self._print)
        menu.addAction("Excel…", lambda: self._export("xlsx"))
        more.setMenu(menu)
        self.new_btn = button("Novo pedido", "primary", t, "fa6s.plus", "on_acc")
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
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_sale(r))
        self.new_btn.clicked.connect(lambda: self.open_sale(None))

    def _view_changed(self, i: int):
        self.view = self.group.button(i).property("view")
        self.status.setVisible(self.view == "orders")
        self.search.setVisible(self.view == "orders")
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
        mono = theme.mono_font()
        with Session() as s:
            if self.view == "orders":
                self.rows = sales.list_sales(s, self.profile.id, first, last, self.status.currentData(),
                                             self.search.text())
            else:
                from datetime import date
                self.rows = sales.summary(s, self.profile.id, first or date(2000, 1, 1), last or date(2100, 1, 1),
                                          by=self.view)
        cols = ORDER_COLS if self.view == "orders" else SUM_COLS
        self._columns(cols)
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            if self.view == "orders":
                cells = [str(row.number), row.day.strftime("%d/%m/%y"), row.contact or "—", row.kind_label,
                         row.status_label, str(row.items), money.fmt(row.total, cur) if row.kind == "sale" else "—",
                         money.fmt(row.received, cur) if row.received else ""]
                tone = {"quote": "mut", "canceled": "mut"}.get(row.status)
            else:
                cells = [row.name, stock.fmt_qty(row.quantity, row.unit) if row.quantity else "",
                         money.fmt(row.revenue, cur), money.fmt(row.cost, cur), money.fmt(row.margin, cur),
                         f"{row.margin_pct}%".replace(".", ",") if row.margin_pct is not None else "—"]
                tone = "neg" if row.margin < 0 else None
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if cols[c][2]:
                    item.setFont(mono)
                    item.setTextAlignment(R)
                if tone:
                    from PySide6.QtGui import QBrush, QColor
                    item.setForeground(QBrush(QColor(self.t[tone])))
                if self.view == "orders":
                    item.setToolTip("Dois cliques para abrir o pedido")
                self.table.setItem(r, c, item)
        self.table.setVisible(bool(self.rows))
        self.empty.setVisible(not self.rows)
        self.empty.setText("Nenhum pedido nesse período. Clique em Novo pedido." if self.view == "orders"
                           else "Nenhuma venda confirmada nesse período.")
        self._footer()

    def _footer(self):
        cur = self.profile.currency
        if self.view == "orders":
            ok = [r for r in self.rows if r.status == "confirmed" and r.kind == "sale"]
            total = sum((r.total for r in ok), Decimal(0))
            got = sum((r.received for r in ok), Decimal(0))
            quotes = sum(1 for r in self.rows if r.status == "quote")
            self.footer.setText(f"{len(ok)} {'venda' if len(ok) == 1 else 'vendas'} confirmadas &nbsp;·&nbsp; "
                                f"vendido <b>{money.fmt(total, cur)}</b> &nbsp;·&nbsp; recebido "
                                f"<b>{money.fmt(got, cur)}</b> &nbsp;·&nbsp; a receber "
                                f"<b>{money.fmt(total - got, cur)}</b>"
                                + (f" &nbsp;·&nbsp; {quotes} orçamento{'s' if quotes != 1 else ''} em aberto"
                                   if quotes else ""))
        else:
            rev = sum((r.revenue for r in self.rows), Decimal(0))
            cost = sum((r.cost for r in self.rows), Decimal(0))
            pct = f" ({(rev - cost) * 100 / rev:.1f}%)".replace(".", ",") if rev else ""
            self.footer.setText(f"Receita <b>{money.fmt(rev, cur)}</b> &nbsp;·&nbsp; custo "
                                f"<b>{money.fmt(cost, cur)}</b> &nbsp;·&nbsp; margem <b>{money.fmt(rev - cost, cur)}"
                                f"</b>{pct}")

    def open_sale(self, row: int | None):
        from finora.ui.sale_dialog import SaleDialog
        if row is not None and (self.view != "orders" or not (0 <= row < len(self.rows))):
            return
        with Session() as s:
            if not stock.list_items(s, self.profile.id):
                self.message.emit("Cadastre os produtos em Estoque antes de vender.")
                return
        dlg = SaleDialog(self, self.profile.id, self.profile.currency, self.t,
                         self.rows[row].id if row is not None else None)
        if dlg.exec() and dlg.done_text:
            self.message.emit(dlg.done_text)
        self.refresh()

    def export_sheet(self) -> export.Sheet:
        cur = self.profile.currency
        if self.view == "orders":
            sheet = export.Sheet("Pedidos de venda", self.period.currentText(),
                                 ["Nº", "Data", "Cliente", "Tipo", "Situação", "Total", "Recebido"], currency=cur)
            for r in self.rows:
                sheet.add([str(r.number), r.day, r.contact, r.kind_label, r.status_label,
                           r.total if r.kind == "sale" else None, r.received or None])
        else:
            sheet = export.Sheet(f"Vendas {VIEWS[self.view].lower()}", self.period.currentText(),
                                 ["Nome", "Quantidade", "Receita", "Custo", "Margem", "Margem %"], currency=cur)
            for r in self.rows:
                sheet.add([r.name, stock.fmt_qty(r.quantity, r.unit) if r.quantity else "", r.revenue, r.cost,
                           r.margin, f"{r.margin_pct}%".replace(".", ",") if r.margin_pct is not None else ""])
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
