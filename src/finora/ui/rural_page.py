"""Tela Agricultura (módulo "rural"): atividades por área, cadastro de propriedades e áreas, custo por área."""
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
from finora.services import export, reports, rural, stock
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, help_icon

R = Qt.AlignRight | Qt.AlignVCenter
L = Qt.AlignLeft | Qt.AlignVCenter
VIEWS = {"activities": "Atividades", "areas": "Áreas", "costs": "Custo por área"}
ACT_COLS = [("DATA", 80, False), ("ÁREA", 200, False), ("ATIVIDADE", 150, False), ("DESCRIÇÃO", None, False),
            ("INSUMOS", None, False), ("COLHIDO", 160, False), ("CUSTO", 110, True)]
AREA_COLS = [("PROPRIEDADE", 160, False), ("ÁREA", None, False), ("TIPO", 130, False), ("CULTURA", None, False),
             ("HECTARES", 90, True), ("PLANTAS/COLMEIAS", 120, True), ("CUSTO A APROPRIAR", 140, True)]
COST_COLS = [("ÁREA", None, False), ("CULTURA", 160, False), ("HECTARES", 80, True), ("INSUMOS", 110, True),
             ("OUTROS", 110, True), ("TOTAL", 120, True), ("POR HECTARE", 110, True), ("COLHIDO", 170, False)]
PERIODS = {**reports.LIST_PERIODS, "all": "Todo o período"}


class RuralPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.rows: list = []
        self.view = "activities"

        self.group = QButtonGroup(self, exclusive=True)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        for i, (k, label) in enumerate(VIEWS.items()):
            b = QPushButton(label, checkable=True, checked=(k == "activities"))
            b.setProperty("variant", "pill")
            b.setProperty("view", k)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            bar.addWidget(b)
        bar.addSpacing(theme.SP_M)
        self.farm = QComboBox()
        self.period = QComboBox()
        for k, label in PERIODS.items():
            self.period.addItem(label, k)
        self.kind = QComboBox()
        self.kind.addItem("Todas as atividades", None)
        for k, label in rural.ACTIVITIES.items():
            self.kind.addItem(label, k)
        self.search = QLineEdit(placeholderText="Área ou descrição…", clearButtonEnabled=True)
        self.search.setMaximumWidth(170)
        for w in (self.farm, self.period, self.kind, self.search):
            bar.addWidget(w)
        bar.addWidget(help_icon("Cada atividade numa área (adubação, poda, colheita…) tira do estoque os insumos usados,\n"
                                "pelo custo médio. Outros custos (mão de obra, máquina) entram no custo da área.\n"
                                "Na colheita, o produto entra no estoque levando o custo que a área acumulou.", t))
        bar.addStretch(1)
        more = button("Mais", "secondary", t, "fa6s.ellipsis", "fg")
        menu = QMenu(more)
        menu.addAction("Nova propriedade…", self.new_farm)
        self.edit_farm_act = menu.addAction("Editar a propriedade escolhida…", self.edit_farm)
        menu.addAction("Nova área…", lambda: self.open_area(None))
        menu.addSeparator()
        menu.addAction("Imprimir…", self._print)
        menu.addAction("Excel…", lambda: self._export("xlsx"))
        more.setMenu(menu)
        self.new_btn = button("Nova atividade", "primary", t, "fa6s.plus", "on_acc")
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
        for w in (self.farm, self.period, self.kind):
            w.currentIndexChanged.connect(lambda _i: self.refresh())
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.table.cellDoubleClicked.connect(lambda r, _c: self._open_row(r))
        self.new_btn.clicked.connect(lambda: self.open_activity(None))
        self._fill_farms()

    def _fill_farms(self, keep: int | None = None):
        keep = keep if keep is not None else self.farm.currentData()
        with Session() as s:
            farms = rural.farms(s, self.profile.id)
        self.farm.blockSignals(True)
        self.farm.clear()
        self.farm.addItem("Todas as propriedades", None)
        for f in farms:
            self.farm.addItem(f.name, f.id)
        self.farm.setCurrentIndex(max(0, self.farm.findData(keep)))
        self.farm.blockSignals(False)

    def _view_changed(self, i: int):
        self.view = self.group.button(i).property("view")
        self.kind.setVisible(self.view == "activities")
        self.search.setVisible(self.view == "activities")
        self.period.setVisible(self.view != "areas")
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

    def _ha(self, v) -> str:
        return stock.fmt_qty(v) if v is not None else ""

    def refresh(self):
        first, last = self._range()
        cur = self.profile.currency
        farm = self.farm.currentData()
        with Session() as s:
            has_area = bool(rural.areas(s, self.profile.id))
            if self.view == "activities":
                self.rows = rural.list_activities(s, self.profile.id, first, last, farm_id=farm,
                                                  kind=self.kind.currentData(), search=self.search.text())
            elif self.view == "areas":
                self.rows = rural.areas(s, self.profile.id, farm_id=farm, include_inactive=True)
            else:
                self.rows = rural.area_costs(s, self.profile.id, first or date(2000, 1, 1), last or date(2100, 1, 1),
                                             farm_id=farm)
        self.edit_farm_act.setEnabled(farm is not None)
        cols = {"activities": ACT_COLS, "areas": AREA_COLS, "costs": COST_COLS}[self.view]
        self._columns(cols)
        self.table.setRowCount(len(self.rows))
        mono = theme.mono_font()
        for r, row in enumerate(self.rows):
            tone = None
            if self.view == "activities":
                cells = [row.day.strftime("%d/%m/%y"), row.area, row.kind_label, row.description, row.text("inputs"),
                         row.text("harvest"), money.fmt(row.total_cost, cur) if row.total_cost else ""]
                tone = "mut" if row.kind == "occurrence" else None
                tip = "Dois cliques para abrir a atividade"
            elif self.view == "areas":
                cells = [row.farm, row.name, row.kind_label, row.crop, self._ha(row.hectares),
                         str(row.units) if row.units else "", money.fmt(row.pending_cost, cur) if row.pending_cost
                         else ""]
                tone = None if row.is_active else "mut"
                tip = "Dois cliques para editar a área"
            else:
                cells = [row.area, row.crop, self._ha(row.hectares), money.fmt(row.inputs_cost, cur),
                         money.fmt(row.other_cost, cur), money.fmt(row.total, cur),
                         money.fmt(row.per_ha, cur) if row.per_ha is not None else "—", row.harvested]
                tip = ""
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if cols[c][2]:
                    item.setFont(mono)
                    item.setTextAlignment(R)
                if tone:
                    item.setForeground(QBrush(QColor(self.t[tone])))
                if tip:
                    item.setToolTip(tip)
                self.table.setItem(r, c, item)
        self.table.setVisible(bool(self.rows))
        self.empty.setVisible(not self.rows)
        if not has_area:
            self.empty.setText("Comece cadastrando a propriedade e as áreas (talhões, pomares, piquetes, apiários) "
                               "em Mais › Nova propriedade e Nova área.")
        else:
            self.empty.setText({"activities": "Nenhuma atividade nesse período. Clique em Nova atividade.",
                                "areas": "Nenhuma área nessa propriedade.",
                                "costs": "Nenhuma atividade nesse período."}[self.view])
        self._footer()

    def _footer(self):
        cur = self.profile.currency
        if self.view == "activities":
            total = sum((r.total_cost for r in self.rows), Decimal(0))
            self.footer.setText(f"{len(self.rows)} {'atividade' if len(self.rows) == 1 else 'atividades'} "
                                f"&nbsp;·&nbsp; custo <b>{money.fmt(total, cur)}</b>")
        elif self.view == "areas":
            ha = sum((r.hectares or 0 for r in self.rows if r.is_active), Decimal(0))
            pend = sum((r.pending_cost for r in self.rows), Decimal(0))
            self.footer.setText(f"{sum(1 for r in self.rows if r.is_active)} áreas ativas &nbsp;·&nbsp; "
                                f"<b>{stock.fmt_qty(ha)} ha</b> &nbsp;·&nbsp; custo a apropriar nas próximas colheitas "
                                f"<b>{money.fmt(pend, cur)}</b>")
        else:
            total = sum((r.total for r in self.rows), Decimal(0))
            self.footer.setText(f"Custo das áreas no período <b>{money.fmt(total, cur)}</b>")

    # ----- abrir -----
    def _open_row(self, r: int):
        if not (0 <= r < len(self.rows)):
            return
        if self.view == "activities":
            self.open_activity(r)
        elif self.view == "areas":
            self.open_area(self.rows[r])

    def open_activity(self, row: int | None):
        from finora.ui.rural_dialogs import ActivityDialog
        with Session() as s:
            if not rural.areas(s, self.profile.id):
                self.message.emit("Cadastre a propriedade e as áreas antes (Mais › Nova propriedade).")
                return
        area_id = None
        if row is None and self.view == "areas" and 0 <= self.table.currentRow() < len(self.rows):
            area_id = self.rows[self.table.currentRow()].id
        dlg = ActivityDialog(self, self.profile.id, self.profile.currency, self.t,
                             self.rows[row].id if row is not None else None, area_id=area_id)
        if dlg.exec() and dlg.done_text:
            self.message.emit(dlg.done_text)
        self.refresh()

    def new_farm(self):
        from finora.ui.rural_dialogs import FarmDialog
        dlg = FarmDialog(self, self.profile.id)
        if dlg.exec():
            self._fill_farms(dlg.saved_id)
            self.message.emit("Propriedade salva. Agora cadastre as áreas dela (Mais › Nova área).")
            self.refresh()

    def edit_farm(self):
        from finora.ui.rural_dialogs import FarmDialog
        fid = self.farm.currentData()
        with Session() as s:
            farm = next((f for f in rural.farms(s, self.profile.id, include_inactive=True) if f.id == fid), None)
        if farm is None:
            return
        if FarmDialog(self, self.profile.id, farm).exec():
            self._fill_farms(fid)
            self.refresh()

    def open_area(self, area: rural.AreaView | None):
        from finora.ui.rural_dialogs import AreaDialog
        with Session() as s:
            if not rural.farms(s, self.profile.id, include_inactive=True):
                self.message.emit("Cadastre a propriedade antes (Mais › Nova propriedade).")
                return
        dlg = AreaDialog(self, self.profile.id, self.t, area, farm_id=self.farm.currentData())
        if dlg.exec():
            self.message.emit("Área salva.")
            self.refresh()

    # ----- exportar -----
    def export_sheet(self) -> export.Sheet:
        cur = self.profile.currency
        sub = " · ".join(x for x in (self.farm.currentText(), self.period.currentText() if self.view != "areas"
                                     else "") if x)
        if self.view == "activities":
            sheet = export.Sheet("Atividades da lavoura", sub, ["Data", "Área", "Atividade", "Descrição", "Insumos",
                                                                "Colhido", "Custo"], currency=cur)
            for r in self.rows:
                sheet.add([r.day, r.area, r.kind_label, r.description, r.text("inputs"), r.text("harvest"),
                           r.total_cost or None])
        elif self.view == "areas":
            sheet = export.Sheet("Áreas", sub, ["Propriedade", "Área", "Tipo", "Cultura", "Hectares",
                                                "Plantas/colmeias", "Custo a apropriar"], currency=cur)
            for r in self.rows:
                sheet.add([r.farm, r.name, r.kind_label, r.crop, self._ha(r.hectares), str(r.units or ""),
                           r.pending_cost or None])
        else:
            sheet = export.Sheet("Custo por área", sub, ["Área", "Cultura", "Hectares", "Insumos", "Outros", "Total",
                                                         "Por hectare", "Colhido"], currency=cur)
            for r in self.rows:
                sheet.add([r.area, r.crop, self._ha(r.hectares), r.inputs_cost, r.other_cost, r.total, r.per_ha,
                           r.harvested])
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
