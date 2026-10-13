"""Janela do lote de produção: insumos usados, produtos obtidos, outros custos; salvar, concluir ou reabrir."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QDateEdit, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import export, production, stock
from finora.services.production import Line, ProductionData
from finora.ui import theme
from finora.ui.stock_dialogs import parse_qty
from finora.ui.widgets import button, field_label, help_icon

R = Qt.AlignRight | Qt.AlignVCenter
CENT = Decimal("0.01")


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class LinesBox(QFrame):
    """Um bloco de itens (insumos ou produtos): escolher o item, quantidade (e % do custo nos produtos)."""

    def __init__(self, title: str, items: list, t: dict, with_share: bool, on_change):
        super().__init__()
        self.items = {i.id: i for i in items}
        self.with_share, self.on_change, self.t = with_share, on_change, t
        self.lines: list[Line] = []
        self.costs: list[Decimal | None] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        head = QLabel(title)
        head.setProperty("role", "total")
        lay.addWidget(head)
        self.add_box = QFrame()
        row = QHBoxLayout(self.add_box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SP_S)
        self.pick = QComboBox(editable=True)
        for it in items:
            self.pick.addItem(f"{it.name} ({it.unit})", it.id)
        self.pick.setInsertPolicy(QComboBox.NoInsert)
        self.pick.completer().setFilterMode(Qt.MatchContains)
        self.pick.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.qty = QLineEdit(placeholderText="Qtd.")
        self.share = QLineEdit(placeholderText="% custo")
        for w in (self.qty, self.share):
            w.setFont(theme.mono_font())
            w.setAlignment(Qt.AlignRight)
            w.setMaximumWidth(90)
        self.add = button("Incluir", "secondary", t, "fa6s.plus", "fg")
        row.addWidget(self.pick, 1)
        row.addWidget(self.qty)
        if with_share:
            row.addWidget(self.share)
            row.addWidget(help_icon("% do custo do lote que vai para esse produto. Deixe em branco em todos para\n"
                                    "dividir pela quantidade (ex.: azeite 90% e bagaço 10%).", t))
        row.addWidget(self.add)
        lay.addWidget(self.add_box)
        self.hint = QLabel()
        self.hint.setProperty("role", "field")
        lay.addWidget(self.hint)
        cols = ["ITEM", "QTD.", "% CUSTO", "CUSTO/UN.", "TOTAL"] if with_share else \
            ["ITEM", "QTD.", "EM ESTOQUE", "CUSTO/UN.", "TOTAL"]
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 100), (2, 100), (3, 100), (4, 110)):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
            hdr.resizeSection(c, w)
            self.table.horizontalHeaderItem(c).setTextAlignment(R)
        lay.addWidget(self.table, 1)
        self.remove = button("Remover selecionado", "link", t, "fa6s.xmark")
        lay.addWidget(self.remove, 0, Qt.AlignLeft)
        self.add.clicked.connect(self.add_line)
        self.qty.returnPressed.connect(self.add_line)
        self.share.returnPressed.connect(self.add_line)
        self.remove.clicked.connect(self.del_line)
        self.pick.currentIndexChanged.connect(self._picked)
        self._picked()

    def set_readonly(self, ro: bool):
        self.add_box.setVisible(not ro)
        self.hint.setVisible(not ro)
        self.remove.setVisible(not ro)

    def _picked(self):
        it = self.items.get(self.pick.currentData())
        if it is None:
            self.hint.setText("Cadastre os itens em Estoque (Novo item).")
            return
        self.hint.setText(f"Em estoque: {stock.fmt_qty(it.balance, it.unit)}"
                          + (f" · custo médio {money.fmt(it.avg_cost.quantize(CENT))}" if it.avg_cost else ""))

    def add_line(self) -> str | None:
        it = self.items.get(self.pick.currentData())
        if it is None:
            return None
        try:
            q = parse_qty(self.qty.text())
            if q <= 0:
                raise ValueError("Quantidade precisa ser maior que zero.")
            share = None
            if self.with_share and self.share.text().strip():
                share = money.parse(self.share.text().replace("%", ""))
        except ValueError as e:
            return self.on_change(str(e))
        self.lines.append(Line(it.id, q, share))
        self.qty.clear()
        self.share.clear()
        self.on_change()
        self.pick.setFocus()
        return None

    def del_line(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.lines):
            del self.lines[r]
            self.on_change()

    def fill(self, costs: list[Decimal | None], currency: str):
        self.table.setRowCount(len(self.lines))
        mono = theme.mono_font()
        for r, ln in enumerate(self.lines):
            it = self.items.get(ln.item_id)
            unit = it.unit if it else ""
            cost = costs[r] if r < len(costs) else None
            third = (f"{ln.share}%".replace(".", ",") if ln.share is not None else "pela qtd.") if self.with_share \
                else stock.fmt_qty(it.balance, unit) if it else ""
            cells = [it.name if it else "?", stock.fmt_qty(ln.quantity, unit), third,
                     money.fmt(cost, currency) if cost is not None else "",
                     money.fmt((Decimal(ln.quantity) * cost).quantize(CENT), currency) if cost is not None else ""]
            short = not self.with_share and it is not None and Decimal(ln.quantity) > it.balance
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c:
                    item.setFont(mono)
                    item.setTextAlignment(R)
                if short and c == 2:
                    item.setToolTip("O estoque não tem tudo o que o lote usa")
                    from PySide6.QtGui import QBrush, QColor
                    item.setForeground(QBrush(QColor(self.t["neg"])))
                self.table.setItem(r, c, item)


class ProductionDialog(QDialog):
    def __init__(self, parent, entity_id: int, currency: str, t: dict, production_id: int | None = None):
        super().__init__(parent)
        self.entity_id, self.currency, self.t = entity_id, currency, t
        self.production_id = production_id
        self.done_text = ""
        self.setObjectName("wizard")
        self.resize(940, 700)
        self.setMinimumSize(760, 560)
        with Session() as s:
            items = stock.list_items(s, entity_id)
            self.locs = [(loc.id, loc.name) for loc in stock.locations(s, entity_id)]
            self.detail = production.get(s, production_id) if production_id else None
            known = {i.id for i in items}
            if self.detail:
                for ln in self.detail.inputs + self.detail.outputs:
                    if ln.item_id not in known:          # item inativado depois: ainda aparece no lote
                        items.append(stock.get_item(s, ln.item_id))
                        known.add(ln.item_id)
        order = {"input": 0, "material": 1, "product": 2, "produced": 3}
        ins = sorted(items, key=lambda i: (order.get(i.kind, 9), i.name.lower()))
        outs = sorted(items, key=lambda i: (-order.get(i.kind, 0), i.name.lower()))
        self.readonly = bool(self.detail and self.detail.status == "done")
        title = f"Lote nº {self.detail.number}" if self.detail else "Novo lote de produção"
        if self.detail:
            title += f" — {production.STATUS[self.detail.status]}"
        self.setWindowTitle(title)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        head = QGridLayout()
        head.setHorizontalSpacing(theme.SP_M)
        head.setVerticalSpacing(3)
        self.name = QLineEdit(maxLength=80, placeholderText="Ex.: Azeite safra 2026 – lote 1")
        self.day = QDateEdit(_qdate(date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.loc = QComboBox()
        for lid, name in self.locs:
            self.loc.addItem(name, lid)
        fields = [("Nome do lote", self.name), ("Data da produção", self.day)]
        if len(self.locs) > 1:
            fields.append(("Local do estoque", self.loc))
        for col, (label, w) in enumerate(fields):
            head.addWidget(field_label(label, t), 0, col)
            head.addWidget(w, 1, col)
        head.setColumnStretch(0, 3)
        lay.addLayout(head)

        self.inputs = LinesBox("Insumos usados (saem do estoque)", ins, t, False, self._changed)
        self.outputs = LinesBox("Produtos obtidos (entram no estoque)", outs, t, True, self._changed)
        lay.addWidget(self.inputs, 1)
        lay.addWidget(self.outputs, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(theme.SP_L)
        left = QGridLayout()
        left.setVerticalSpacing(3)
        self.extra = QLineEdit(placeholderText="0,00")
        self.extra.setFont(theme.mono_font())
        self.extra.setAlignment(Qt.AlignRight)
        self.extra.setMaximumWidth(130)
        extra_lbl = QHBoxLayout()
        extra_lbl.addWidget(field_label("Outros custos do lote", t))
        extra_lbl.addWidget(help_icon("Mão de obra, energia, frete, aluguel de máquina… o que não está no estoque.\n"
                                      "Só entra no custo do produto; os pagamentos continuam em Lançamentos.", t))
        extra_lbl.addStretch(1)
        left.addLayout(extra_lbl, 0, 0)
        left.addWidget(self.extra, 1, 0)
        self.notes = QLineEdit(maxLength=300, placeholderText="Observação (opcional)")
        left.addWidget(self.notes, 2, 0)
        bottom.addLayout(left, 3)
        tot = QGridLayout()
        tot.setVerticalSpacing(3)
        self.in_lbl, self.total_lbl, self.yield_lbl = QLabel(), QLabel(), QLabel()
        for w in (self.in_lbl, self.total_lbl, self.yield_lbl):
            w.setFont(theme.mono_font())
            w.setAlignment(R)
        f = self.total_lbl.font()
        f.setPointSize(13)
        f.setBold(True)
        self.total_lbl.setFont(f)
        self.cost_kind = QLabel()
        tot.addWidget(self.cost_kind, 0, 0)
        tot.addWidget(self.in_lbl, 0, 1)
        tot.addWidget(QLabel("Custo do lote"), 1, 0)
        tot.addWidget(self.total_lbl, 1, 1)
        tot.addWidget(QLabel("Rendimento"), 2, 0)
        tot.addWidget(self.yield_lbl, 2, 1)
        bottom.addLayout(tot, 2)
        lay.addLayout(bottom)

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        self.print_btn = button("Imprimir ficha", "link", t, "fa6s.print")
        self.reopen_btn = button("Reabrir lote", "link", t, "fa6s.rotate-left")
        self.delete_btn = button("Excluir lote", "link", t, "fa6s.trash")
        for w in (self.print_btn, self.reopen_btn, self.delete_btn):
            btns.addWidget(w)
        btns.addStretch(1)
        close = button("Fechar", "secondary")
        self.save_btn = button("Salvar (em andamento)", "secondary")
        self.finish_btn = button("Concluir lote", "primary", t, "fa6s.check", "on_acc")
        for w in (close, self.save_btn, self.finish_btn):
            btns.addWidget(w)
        lay.addLayout(btns)

        close.clicked.connect(self.reject)
        self.save_btn.clicked.connect(lambda: self.save(finish=False))
        self.finish_btn.clicked.connect(lambda: self.save(finish=True))
        self.print_btn.clicked.connect(self.print_sheet)
        self.reopen_btn.clicked.connect(self.do_reopen)
        self.delete_btn.clicked.connect(self.do_delete)
        self.extra.textChanged.connect(lambda _t: self._changed())
        self.day.dateChanged.connect(lambda _d: self._changed())
        self._load()

    # ----- carregar -----
    def _load(self):
        d = self.detail
        if d:
            self.name.setText(d.name)
            self.day.setDate(_qdate(d.day))
            if d.location_id:
                self.loc.setCurrentIndex(max(0, self.loc.findData(d.location_id)))
            self.inputs.lines = [Line(ln.item_id, ln.quantity) for ln in d.inputs]
            self.outputs.lines = [Line(ln.item_id, ln.quantity, ln.share) for ln in d.outputs]
            self.extra.setText(money.fmt(d.extra_cost).split(" ", 1)[-1] if d.extra_cost else "")
            self.notes.setText(d.notes)
        ro = self.readonly
        for w in (self.name, self.day, self.loc, self.extra, self.notes):
            w.setEnabled(not ro)
        self.inputs.set_readonly(ro)
        self.outputs.set_readonly(ro)
        self.save_btn.setVisible(not ro)
        self.finish_btn.setVisible(not ro)
        self.reopen_btn.setVisible(ro)
        self.delete_btn.setVisible(bool(d) and not ro)
        self.print_btn.setVisible(bool(d))
        self._changed()

    def _extra(self) -> Decimal:
        try:
            return money.parse(self.extra.text() or "0")
        except ValueError:
            return Decimal(0)

    def _data(self) -> ProductionData:
        return ProductionData(name=self.name.text(), day=self.day.date().toPython(), inputs=list(self.inputs.lines),
                              outputs=list(self.outputs.lines), extra_cost=self._extra(),
                              location_id=self.loc.currentData() if len(self.locs) > 1 else None,
                              notes=self.notes.text())

    def _changed(self, error: str | None = None):
        if error:
            self._err(error)
            return
        self.error.hide()
        if self.readonly:                                # concluído: custos gravados
            d = self.detail
            in_costs = [ln.unit_cost for ln in d.inputs]
            out_costs = [ln.unit_cost for ln in d.outputs]
            total = d.total_cost or Decimal(0)
            self.cost_kind.setText("Insumos (custo gravado)")
        else:
            d = self._data()
            with Session() as s:
                in_costs = [stock.average_cost(s, self.entity_id, ln.item_id, until=d.day) for ln in d.inputs]
                total, out_costs = production.estimate(s, self.entity_id, d) if d.outputs else \
                    (production.estimate(s, self.entity_id, d)[0], [])
            self.cost_kind.setText("Insumos (prévia, custo médio)")
        self.inputs.fill(in_costs, self.currency)
        self.outputs.fill(out_costs, self.currency)
        ins = sum(((Decimal(ln.quantity) * (c or 0)) for ln, c in zip(self.inputs.lines, in_costs)), Decimal(0))
        self.in_lbl.setText(money.fmt(ins.quantize(CENT), self.currency))
        self.total_lbl.setText(money.fmt(total, self.currency))
        names = {**self.inputs.items, **self.outputs.items}

        def trip(lines):
            return [(names[ln.item_id].name, ln.quantity, names[ln.item_id].unit) for ln in lines
                    if ln.item_id in names]
        self.yield_lbl.setText(production._yield_text(trip(self.inputs.lines), trip(self.outputs.lines)) or "—")
        self.yield_lbl.setToolTip("Produto principal (1º da lista) sobre o insumo principal (1º da lista)")

    # ----- gravar -----
    def _err(self, text: str):
        self.error.setText(text)
        self.error.show()

    def save(self, finish: bool):
        if finish and QMessageBox.question(
                self, "Concluir lote", "Concluir o lote? Os insumos saem do estoque e os produtos entram, com o custo "
                                       "calculado.\n\nSe precisar corrigir depois, use Reabrir lote.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        try:
            with Session() as s:
                self.production_id = production.save(s, self.entity_id, self._data(), self.production_id)
                number = s.get(production.Production, self.production_id).number
                total = production.finish(s, self.production_id) if finish else None
        except ValueError as e:
            self._err(str(e))
            return
        self.done_text = (f"Lote {number} concluído: custo {money.fmt(total, self.currency)}, produtos no estoque."
                          if finish else f"Lote {number} salvo (em andamento).")
        self.accept()

    def do_reopen(self):
        if QMessageBox.question(self, "Reabrir lote",
                                f"Reabrir o lote nº {self.detail.number}?\n\nOs insumos voltam ao estoque e os produtos "
                                "saem, até você concluir de novo.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            with Session() as s:
                production.reopen(s, self.detail.id)
        except ValueError as e:
            self._err(str(e))
            return
        self.done_text = f"Lote {self.detail.number} reaberto."
        self.accept()

    def do_delete(self):
        if QMessageBox.question(self, "Excluir lote", f"Excluir o lote nº {self.detail.number}?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        with Session() as s:
            production.delete(s, self.detail.id)
        self.done_text = f"Lote {self.detail.number} excluído."
        self.accept()

    def batch_sheet(self) -> export.Sheet:
        d = self.detail
        sheet = export.Sheet(f"Lote de produção nº {d.number} — {d.name}",
                             f"{d.day:%d/%m/%Y} · {production.STATUS[d.status]}",
                             ["Item", "Quantidade", "Custo/un.", "Total"], currency=self.currency)
        sheet.add(["Insumos usados", "", None, None], "bold")
        for ln in d.inputs:
            sheet.add([ln.name, stock.fmt_qty(ln.quantity, ln.unit), ln.unit_cost, ln.total], "indent")
        if d.extra_cost:
            sheet.add(["Outros custos", "", None, d.extra_cost], "indent")
        if d.total_cost is not None:
            sheet.add(["Custo do lote", "", None, d.total_cost], "bold")
        sheet.add(["Produtos obtidos", "", None, None], "bold")
        for ln in d.outputs:
            sheet.add([ln.name, stock.fmt_qty(ln.quantity, ln.unit), ln.unit_cost, ln.total], "indent")
        foot = [f"Rendimento: {d.yield_text}" if d.yield_text else "", d.notes]
        sheet.footer = " · ".join(x for x in foot if x)
        return sheet

    def print_sheet(self):
        from finora.ui import printing
        printing.open_print(self, self.batch_sheet(), self.t)
