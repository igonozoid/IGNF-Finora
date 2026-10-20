"""Tela Pecuária (módulo "livestock"): rebanho por lote, registros e custo por lote."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import export, livestock, reports, stock
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, help_icon

R = Qt.AlignRight | Qt.AlignVCenter
L = Qt.AlignLeft | Qt.AlignVCenter
VIEWS = {"lots": "Rebanho", "events": "Registros", "costs": "Custo por lote"}
LOT_COLS = [("LOTE", None, False), ("ESPÉCIE", 90, False), ("CATEGORIA", 100, False), ("PIQUETE", None, False),
            ("CABEÇAS", 80, True), ("PESO MÉDIO", 100, True), ("PESADO EM", 90, False), ("GMD", 90, True)]
EVENT_COLS = [("DATA", 80, False), ("LOTE", 170, False), ("REGISTRO", 170, False), ("CABEÇAS", 75, True),
              ("DETALHES", None, False), ("VALOR", 110, True), ("CUSTO", 100, True)]
COST_COLS = [("LOTE", None, False), ("CABEÇAS HOJE", 95, True), ("NASC.", 60, True), ("MORTES", 65, True),
             ("COMPRAS", 120, True), ("VENDAS", 120, True), ("SANIDADE E TRATO", 130, True),
             ("CUSTO/CABEÇA", 110, True)]
PERIODS = {**reports.LIST_PERIODS, "all": "Todo o período"}


class LivestockPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.rows: list = []
        self.view = "lots"

        self.group = QButtonGroup(self, exclusive=True)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        for i, (k, label) in enumerate(VIEWS.items()):
            b = QPushButton(label, checkable=True, checked=(k == "lots"))
            b.setProperty("variant", "pill")
            b.setProperty("view", k)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            bar.addWidget(b)
        bar.addSpacing(theme.SP_M)
        self.lot = QComboBox()
        self.period = QComboBox()
        for k, label in PERIODS.items():
            self.period.addItem(label, k)
        self.kind = QComboBox()
        self.kind.addItem("Todos os registros", None)
        for k, label in livestock.EVENTS.items():
            self.kind.addItem(label, k)
        for w in (self.lot, self.period, self.kind):
            bar.addWidget(w)
        bar.addWidget(help_icon("O rebanho é controlado por lote. As cabeças saem dos registros: nascimento, compra e\n"
                                "transferência que entra somam; venda, morte e transferência que sai subtraem.\n"
                                "Sanidade e alimentação tiram os insumos do estoque. Duas pesagens dão o GMD\n"
                                "(ganho médio diário).", t))
        bar.addStretch(1)
        more = button("Mais", "secondary", t, "fa6s.ellipsis", "fg")
        menu = QMenu(more)
        menu.addAction("Novo lote…", lambda: self.open_lot(None))
        self.edit_lot_act = menu.addAction("Editar o lote selecionado…", self._edit_selected_lot)
        menu.addSeparator()
        menu.addAction("Imprimir…", self._print)
        menu.addAction("Excel…", lambda: self._export("xlsx"))
        menu.addAction("CSV…", lambda: self._export("csv"))
        more.setMenu(menu)
        self.new_btn = button("Novo registro", "primary", t, "fa6s.plus", "on_acc")
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
        for w in (self.lot, self.period, self.kind):
            w.currentIndexChanged.connect(lambda _i: self.refresh())
        self.table.cellDoubleClicked.connect(lambda r, _c: self._open_row(r))
        self.new_btn.clicked.connect(lambda: self.open_event(None))
        self._fill_lots()
        self._view_changed(0)

    def _fill_lots(self, keep: int | None = None):
        keep = keep if keep is not None else self.lot.currentData()
        with Session() as s:
            all_lots = livestock.lots(s, self.profile.id)
        self.lot.blockSignals(True)
        self.lot.clear()
        self.lot.addItem("Todos os lotes", None)
        for lv in all_lots:
            self.lot.addItem(lv.name, lv.id)
        self.lot.setCurrentIndex(max(0, self.lot.findData(keep)))
        self.lot.blockSignals(False)

    def _view_changed(self, i: int):
        self.view = self.group.button(i).property("view")
        self.lot.setVisible(self.view == "events")
        self.kind.setVisible(self.view == "events")
        self.period.setVisible(self.view != "lots")
        self.edit_lot_act.setEnabled(self.view == "lots")
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
            has_lot = bool(livestock.lots(s, self.profile.id, include_inactive=True))
            if self.view == "lots":
                self.rows = livestock.lots(s, self.profile.id, include_inactive=True)
            elif self.view == "events":
                self.rows = livestock.list_events(s, self.profile.id, first, last, lot_id=self.lot.currentData(),
                                                  kind=self.kind.currentData())
            else:
                self.rows = livestock.lot_costs(s, self.profile.id, first or date(2000, 1, 1),
                                                last or date(2100, 1, 1))
        cols = {"lots": LOT_COLS, "events": EVENT_COLS, "costs": COST_COLS}[self.view]
        self._columns(cols)
        self.table.setRowCount(len(self.rows))
        mono = theme.mono_font()
        for r, row in enumerate(self.rows):
            tone = None
            if self.view == "lots":
                cells = [row.name, row.species_label, row.category, row.area or "—", str(row.heads),
                         f"{stock.fmt_qty(row.weight)} kg" if row.weight is not None else "",
                         row.weighed_on.strftime("%d/%m/%y") if row.weighed_on else "",
                         f"{stock.fmt_qty(row.daily_gain)} kg/dia" if row.daily_gain is not None else ""]
                tone = None if row.is_active else "mut"
                tip = "Dois cliques para ver os registros do lote"
            elif self.view == "events":
                cells = [row.day.strftime("%d/%m/%y"), row.lot, row.kind_label,
                         f"{row.heads:+d}" if row.heads else "", row.detail,
                         money.fmt(row.value, cur) if row.value else "", money.fmt(row.cost, cur) if row.cost else ""]
                tone = "neg" if row.kind == "death" else None
                tip = "Dois cliques para abrir o registro"
            else:
                cells = [row.lot, str(row.heads), str(row.births or ""), str(row.deaths or ""),
                         money.fmt(row.purchases, cur) if row.purchases else "",
                         money.fmt(row.sales, cur) if row.sales else "", money.fmt(row.cost, cur),
                         money.fmt(row.per_head, cur) if row.per_head is not None else "—"]
                tip = "Sanidade e trato = insumos usados + outros custos dos registros do período"
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if cols[c][2]:
                    item.setFont(mono)
                    item.setTextAlignment(R)
                if tone:
                    item.setForeground(QBrush(QColor(self.t[tone])))
                item.setToolTip(tip)
                self.table.setItem(r, c, item)
        self.table.setVisible(bool(self.rows))
        self.empty.setVisible(not self.rows)
        if not has_lot:
            self.empty.setText("Comece cadastrando os lotes em Mais › Novo lote (ex.: Vacas de cria, Recria 2026). "
                               "Os piquetes são as áreas da Agricultura.")
        else:
            self.empty.setText({"lots": "Nenhum lote.", "events": "Nenhum registro nesse período.",
                                "costs": "Nenhum registro nesse período."}[self.view])
        self._footer()

    def _footer(self):
        cur = self.profile.currency
        if self.view == "lots":
            total = sum(r.heads for r in self.rows)
            by: dict[str, int] = {}
            for r in self.rows:
                if r.heads:
                    by[r.species_label] = by.get(r.species_label, 0) + r.heads
            detail = " · ".join(f"{k}: {v}" for k, v in sorted(by.items()))
            self.footer.setText(f"<b>{total}</b> cabeças" + (f" &nbsp;·&nbsp; {detail}" if len(by) > 1 else ""))
        elif self.view == "events":
            cost = sum((r.cost for r in self.rows), Decimal(0))
            self.footer.setText(f"{len(self.rows)} registros &nbsp;·&nbsp; custo <b>{money.fmt(cost, cur)}</b>")
        else:
            cost = sum((r.cost for r in self.rows), Decimal(0))
            sales = sum((r.sales for r in self.rows), Decimal(0))
            buys = sum((r.purchases for r in self.rows), Decimal(0))
            self.footer.setText(f"Compras <b>{money.fmt(buys, cur)}</b> &nbsp;·&nbsp; vendas "
                                f"<b>{money.fmt(sales, cur)}</b> &nbsp;·&nbsp; sanidade e trato "
                                f"<b>{money.fmt(cost, cur)}</b>")

    # ----- abrir -----
    def _open_row(self, r: int):
        if not (0 <= r < len(self.rows)):
            return
        if self.view == "events":
            self.open_event(r)
        elif self.view == "lots":                     # vai para os registros do lote
            self.group.button(1).setChecked(True)
            self._fill_lots(self.rows[r].id)
            self.period.setCurrentIndex(self.period.findData("all"))
            self._view_changed(1)

    def _edit_selected_lot(self):
        r = self.table.currentRow()
        if self.view == "lots" and 0 <= r < len(self.rows):
            self.open_lot(self.rows[r])

    def open_lot(self, lot):
        from finora.ui.livestock_dialogs import LotDialog
        dlg = LotDialog(self, self.profile.id, lot)
        if dlg.exec():
            self._fill_lots()
            self.message.emit("Lote salvo.")
            self.refresh()

    def open_event(self, row: int | None):
        from finora.ui.livestock_dialogs import EventDialog
        with Session() as s:
            if not livestock.lots(s, self.profile.id):
                self.message.emit("Cadastre os lotes antes (Mais › Novo lote).")
                return
        lot_id = self.lot.currentData() if self.view == "events" else None
        if row is None and self.view == "lots" and 0 <= self.table.currentRow() < len(self.rows):
            lot_id = self.rows[self.table.currentRow()].id
        dlg = EventDialog(self, self.profile.id, self.profile.currency, self.t,
                          self.rows[row].id if row is not None else None, lot_id=lot_id)
        if dlg.exec() and dlg.done_text:
            self.message.emit(dlg.done_text)
        self.refresh()

    # ----- exportar -----
    def export_sheet(self) -> export.Sheet:
        cur = self.profile.currency
        if self.view == "lots":
            sheet = export.Sheet("Rebanho", date.today().strftime("%d/%m/%Y"),
                                 ["Lote", "Espécie", "Categoria", "Piquete", "Cabeças", "Peso médio (kg)",
                                  "Pesado em", "GMD (kg/dia)"], currency=cur)
            for r in self.rows:
                sheet.add([r.name, r.species_label, r.category, r.area, str(r.heads),
                           stock.fmt_qty(r.weight) if r.weight is not None else "", r.weighed_on,
                           stock.fmt_qty(r.daily_gain) if r.daily_gain is not None else ""])
        elif self.view == "events":
            sheet = export.Sheet("Registros do rebanho", " · ".join((self.lot.currentText(),
                                                                     self.period.currentText())),
                                 ["Data", "Lote", "Registro", "Cabeças", "Detalhes", "Valor", "Custo"], currency=cur)
            for r in self.rows:
                sheet.add([r.day, r.lot, r.kind_label, f"{r.heads:+d}" if r.heads else "", r.detail,
                           r.value or None, r.cost or None])
        else:
            sheet = export.Sheet("Custo por lote", self.period.currentText(),
                                 ["Lote", "Cabeças hoje", "Nascimentos", "Mortes", "Compras", "Vendas",
                                  "Sanidade e trato", "Custo/cabeça"], currency=cur)
            for r in self.rows:
                sheet.add([r.lot, str(r.heads), str(r.births), str(r.deaths), r.purchases, r.sales, r.cost,
                           r.per_head])
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
            show_upgrade(self, "Exportar para Excel, PDF e CSV é um recurso das edições Plus e Pro.")
            return
        path = exporting.run(self, self.export_sheet(), kind)
        if path:
            self.message.emit(f"Salvo em {path}")

    def apply_theme(self, t: dict):
        self.t = t
        if self.isVisible():
            self.refresh()
