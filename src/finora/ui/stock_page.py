"""Tela Estoque (módulo "stock"): itens com saldo e custo médio, cadastro e histórico do item, movimentos."""
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import export, stock
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, field_label, help_icon, set_tone

R = Qt.AlignRight | Qt.AlignVCenter
L = Qt.AlignLeft | Qt.AlignVCenter
PANEL_W = 340
COLS = [("CÓDIGO", 80, False), ("ITEM", None, False), ("TIPO", 150, False), ("UN.", 60, False),
        ("SALDO", 100, True), ("MÍNIMO", 80, True), ("CUSTO MÉDIO", 110, True), ("EM ESTOQUE", 120, True)]


def _table(cols) -> QTableWidget:
    tv = QTableWidget(0, len(cols))
    tv.setHorizontalHeaderLabels([c[0] for c in cols])
    tv.verticalHeader().hide()
    tv.verticalHeader().setDefaultSectionSize(theme.ROW_H)
    tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tv.setSelectionBehavior(QAbstractItemView.SelectRows)
    tv.setSelectionMode(QAbstractItemView.SingleSelection)
    tv.setShowGrid(False)
    tv.setWordWrap(False)
    hdr = tv.horizontalHeader()
    hdr.setHighlightSections(False)
    for i, (_t, w, right) in enumerate(cols):
        if w is None:
            hdr.setSectionResizeMode(i, QHeaderView.Stretch)
        else:
            hdr.setSectionResizeMode(i, QHeaderView.Fixed)
            hdr.resizeSection(i, w)
        tv.horizontalHeaderItem(i).setTextAlignment(R if right else L)
    return tv


class StockPage(QWidget):
    message = Signal(str)
    open_entry = Signal(int)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.items: list[stock.ItemView] = []
        self.current: stock.ItemView | None = None
        self.moves: list[stock.MoveView] = []

        # barra
        self.search = QLineEdit(placeholderText="Procurar item ou código…", clearButtonEnabled=True)
        self.search.setMaximumWidth(220)
        self.search.setMinimumWidth(150)
        self.kind_box = QComboBox()
        self.kind_box.addItem("Todos os tipos", None)
        for k, label in stock.KINDS.items():
            self.kind_box.addItem(label, k)
        self.loc_box = QComboBox()
        self.loc_box.setMinimumWidth(140)
        self.low_only = QCheckBox("Abaixo do mínimo")
        self.in_btn = button("Entrada", "primary", t, "fa6s.arrow-down", "on_acc")
        self.out_btn = button("Saída", "secondary", t, "fa6s.arrow-up", "fg")
        more = button("Mais", "secondary", t, "fa6s.ellipsis", "fg")
        menu = QMenu(more)
        menu.addAction("Perda…", lambda: self.open_move("loss"))
        menu.addAction("Inventário (contagem)…", lambda: self.open_move("adjust"))
        menu.addAction("Transferir entre locais…", lambda: self.open_move("transfer"))
        menu.addSeparator()
        menu.addAction("Locais de estoque…", self.open_locations)
        menu.addSeparator()
        menu.addAction("Imprimir…", self._print)
        menu.addAction("Exportar Excel…", lambda: self._export("xlsx"))
        menu.addAction("Exportar CSV…", lambda: self._export("csv"))
        more.setMenu(menu)
        self.new_btn = button("Novo item", "secondary", t, "fa6s.plus", "fg")
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        for w in (self.search, self.kind_box, self.loc_box, self.low_only):
            bar.addWidget(w)
        bar.addWidget(help_icon("Produtos que você vende, insumos que usa para produzir e materiais de uso interno\n"
                                "(do escritório, da fazenda). O saldo e o custo médio saem dos movimentos.\n"
                                "Entrada com custo pode ir direto para Contas a pagar.", t))
        bar.addStretch(1)
        for w in (self.new_btn, self.in_btn, self.out_btn, more):
            bar.addWidget(w)

        self.table = _table(COLS)
        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.footer = QLabel()
        self.footer.setTextFormat(Qt.RichText)

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addLayout(bar)
        left.addWidget(self.table, 1)
        left.addWidget(self.empty, 1)
        left.addWidget(self.footer)

        # painel: detalhe do item | formulário
        self.panel = QStackedWidget()
        self.panel.setFixedWidth(PANEL_W)
        self.panel.addWidget(self._build_detail())
        self.panel.addWidget(self._build_form())

        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addLayout(left, 1)
        root.addWidget(self.panel)

        self.search.textChanged.connect(lambda _t: self.refresh())
        self.kind_box.currentIndexChanged.connect(lambda _i: self.refresh())
        self.loc_box.currentIndexChanged.connect(lambda _i: self.refresh())
        self.low_only.toggled.connect(lambda _on: self.refresh())
        self.table.itemSelectionChanged.connect(self._picked)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.edit_item())
        self.new_btn.clicked.connect(self.new_item)
        self.in_btn.clicked.connect(lambda: self.open_move("in"))
        self.out_btn.clicked.connect(lambda: self.open_move("out"))

    # ---------- painel de detalhe ----------
    def _build_detail(self) -> QWidget:
        card = QFrame(objectName="card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        lay.setSpacing(theme.SP_M)
        self.d_title = QLabel(objectName="sectionTitle", wordWrap=True)
        self.d_sub = QLabel(wordWrap=True)
        self.d_sub.setProperty("role", "field")
        self.d_balance = QLabel()
        self.d_balance.setFont(theme.mono_font())
        f = self.d_balance.font()
        f.setPointSize(14)
        self.d_balance.setFont(f)
        self.d_info = QLabel(wordWrap=True)
        self.d_info.setProperty("role", "muted")
        row = QHBoxLayout()
        self.edit_btn = button("Editar", "link", self.t, "fa6s.pen")
        self.d_in = button("Entrada", "link", self.t, "fa6s.arrow-down")
        self.d_out = button("Saída", "link", self.t, "fa6s.arrow-up")
        row.addWidget(self.edit_btn)
        row.addStretch(1)
        row.addWidget(self.d_in)
        row.addWidget(self.d_out)
        self.hist = _table([("DATA", 64, False), ("MOVIMENTO", None, False), ("QTD.", 70, True), ("SALDO", 70, True)])
        self.del_move = button("Excluir movimento selecionado", "link", self.t, "fa6s.trash-can")
        self.d_empty = QLabel("Escolha um item na lista, ou cadastre o primeiro em Novo item.", wordWrap=True,
                              alignment=Qt.AlignCenter)
        self.d_empty.setProperty("role", "muted")
        for w in (self.d_title, self.d_sub, self.d_balance, self.d_info):
            lay.addWidget(w)
        lay.addLayout(row)
        lay.addWidget(field_label("Movimentos", self.t))
        lay.addWidget(self.hist, 1)
        lay.addWidget(self.del_move, 0, Qt.AlignLeft)
        lay.addWidget(self.d_empty, 1)
        self.edit_btn.clicked.connect(self.edit_item)
        self.d_in.clicked.connect(lambda: self.open_move("in"))
        self.d_out.clicked.connect(lambda: self.open_move("out"))
        self.del_move.clicked.connect(self.delete_move)
        self.hist.cellDoubleClicked.connect(self._hist_double)
        return card

    def _show_detail(self):
        it = self.current
        has = it is not None
        for w in (self.d_title, self.d_sub, self.d_balance, self.d_info, self.edit_btn, self.d_in, self.d_out,
                  self.hist, self.del_move):
            w.setVisible(has)
        self.d_empty.setVisible(not has)
        self.panel.setCurrentIndex(0)
        if not has:
            return
        self.d_title.setText(it.name + ("" if it.is_active else " (inativo)"))
        self.d_sub.setText(" · ".join(x for x in (it.kind_label, it.code and f"código {it.code}", it.unit) if x))
        self.d_balance.setText(stock.fmt_qty(it.balance, it.unit))
        set_tone(self.d_balance, "neg" if it.below_min or it.balance < 0 else None)
        info = []
        if it.avg_cost:
            info.append(f"Custo médio {money.fmt(it.avg_cost.quantize(Decimal('0.01')))} · em estoque "
                        f"{money.fmt(it.value)}")
        if it.min_stock is not None:
            info.append(f"Mínimo {stock.fmt_qty(it.min_stock, it.unit)}" + (" — abaixo do mínimo!" if it.below_min
                                                                             else ""))
        if it.sale_price:
            info.append(f"Preço de venda {money.fmt(it.sale_price)}")
        if it.notes:
            info.append(it.notes)
        self.d_info.setText("\n".join(info))
        with Session() as s:
            self.moves = stock.history(s, self.profile.id, it.id, self.loc_box.currentData())
        self.hist.setRowCount(len(self.moves))
        mono = theme.mono_font()
        for r, m in enumerate(self.moves):
            label = m.kind_label + (f" · {m.contact}" if m.contact else "") + (f" · {m.notes}" if m.notes else "")
            if m.kind == "transfer":
                label = f"Transferência · {'saiu de' if m.quantity < 0 else 'entrou em'} {m.location}"
            cells = [m.day.strftime("%d/%m/%y"), label,
                     ("+" if m.quantity > 0 else "") + stock.fmt_qty(m.quantity), stock.fmt_qty(m.balance)]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c >= 2:
                    item.setFont(mono)
                    item.setTextAlignment(R)
                tip = [m.location]
                if m.unit_cost is not None:
                    tip.append(f"custo {money.fmt(Decimal(m.unit_cost).quantize(Decimal('0.01')))}/{it.unit}")
                if m.document_no:
                    tip.append(f"documento {m.document_no}")
                if m.entry_id:
                    tip.append("dois cliques: abre o lançamento da compra")
                item.setToolTip(" · ".join(tip))
                self.hist.setItem(r, c, item)
        self.del_move.setEnabled(bool(self.moves))

    def _hist_double(self, row: int, _col: int):
        if 0 <= row < len(self.moves) and self.moves[row].entry_id:
            self.open_entry.emit(self.moves[row].entry_id)

    # ---------- formulário do item ----------
    def _build_form(self) -> QWidget:
        card = QFrame(objectName="card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        lay.setSpacing(3)
        self.f_title = QLabel(objectName="sectionTitle")
        lay.addWidget(self.f_title)
        lay.addSpacing(theme.SP_S)
        self.f_name = QLineEdit(maxLength=120, placeholderText="Ex.: Azeite extravirgem 500 mL")
        self.f_code = QLineEdit(maxLength=30, placeholderText="Opcional")
        self.f_kind = QComboBox()
        for k, label in stock.KINDS.items():
            self.f_kind.addItem(label, k)
        self.f_unit = QComboBox(editable=True)
        self.f_unit.addItems(stock.UNITS)
        self.f_price = QLineEdit(placeholderText="0,00")
        self.f_min = QLineEdit(placeholderText="Opcional")
        for w in (self.f_price, self.f_min):
            w.setFont(theme.mono_font())
            w.setAlignment(Qt.AlignRight)
        self.f_cat = QComboBox()
        self.f_notes = QLineEdit(maxLength=300, placeholderText="Opcional")
        self.f_active = QCheckBox("Ativo")
        self.price_lbl = field_label("Preço de venda", self.t)
        self.cat_lbl = field_label("Categoria financeira", self.t, "Usada quando a compra (ou a venda) vira lançamento.")
        for label, w in ((field_label("Nome", self.t), self.f_name), (field_label("Tipo", self.t), self.f_kind),
                         (field_label("Unidade", self.t), self.f_unit), (field_label("Código", self.t), self.f_code),
                         (self.price_lbl, self.f_price),
                         (field_label("Estoque mínimo", self.t, "Abaixo disso o item aparece em vermelho e no "
                                                               "filtro \"Abaixo do mínimo\"."), self.f_min),
                         (self.cat_lbl, self.f_cat), (field_label("Observação", self.t), self.f_notes)):
            lay.addWidget(label)
            lay.addWidget(w)
        lay.addWidget(self.f_active)
        self.f_error = QLabel(wordWrap=True)
        self.f_error.setProperty("role", "error")
        self.f_error.hide()
        lay.addWidget(self.f_error)
        lay.addStretch(1)
        row = QHBoxLayout()
        save = button("Salvar", "primary")
        cancel = button("Cancelar", "secondary")
        row.addWidget(save)
        row.addWidget(cancel)
        row.addStretch(1)
        lay.addLayout(row)
        save.clicked.connect(self.save_item)
        cancel.clicked.connect(self._show_detail)
        self.f_kind.currentIndexChanged.connect(self._kind_changed)
        self.editing: stock.ItemView | None = None
        return card

    def _kind_changed(self):
        sells = self.f_kind.currentData() in ("product", "produced")
        self.price_lbl.setVisible(sells)
        self.f_price.setVisible(sells)
        from finora.ui import category_pick
        category_pick.fill(self.f_cat, self.profile.id, "income" if sells else "expense", self.f_cat.currentData(),
                           empty="Nenhuma", t=self.t)

    def new_item(self):
        self.editing = None
        self.f_title.setText("Novo item")
        for w in (self.f_name, self.f_code, self.f_price, self.f_min, self.f_notes):
            w.clear()
        self.f_kind.setCurrentIndex(0)
        self.f_unit.setCurrentText("un")
        self.f_active.setChecked(True)
        self.f_active.hide()
        self._kind_changed()
        self.f_error.hide()
        self.panel.setCurrentIndex(1)
        self.f_name.setFocus()

    def edit_item(self):
        it = self.current
        if it is None:
            return
        self.editing = it
        self.f_title.setText("Editar item")
        self.f_name.setText(it.name)
        self.f_code.setText(it.code)
        self.f_kind.setCurrentIndex(max(0, self.f_kind.findData(it.kind)))
        self.f_unit.setCurrentText(it.unit)
        self.f_price.setText(money.fmt(it.sale_price).split(" ", 1)[-1] if it.sale_price is not None else "")
        self.f_min.setText(stock.fmt_qty(it.min_stock) if it.min_stock is not None else "")
        self._kind_changed()
        self.f_cat.setCurrentIndex(max(0, self.f_cat.findData(it.category_id)))
        self.f_notes.setText(it.notes)
        self.f_active.setChecked(it.is_active)
        self.f_active.show()
        self.f_error.hide()
        self.panel.setCurrentIndex(1)

    def save_item(self):
        from finora.ui.stock_dialogs import parse_qty
        try:
            price = money.parse(self.f_price.text()) if self.f_price.isVisible() and self.f_price.text().strip() \
                else None
            minimum = parse_qty(self.f_min.text()) if self.f_min.text().strip() else None
            data = dict(name=self.f_name.text(), kind=self.f_kind.currentData(), unit=self.f_unit.currentText(),
                        code=self.f_code.text(), sale_price=price, min_stock=minimum,
                        category_id=self.f_cat.currentData(), notes=self.f_notes.text())
            with Session() as s:
                if self.editing is None:
                    iid = stock.create_item(s, self.profile.id, **data)
                    msg = "Item cadastrado. Para pôr saldo, use Entrada (ou Inventário)."
                else:
                    iid = self.editing.id
                    stock.update_item(s, iid, is_active=self.f_active.isChecked(), **data)
                    msg = "Item atualizado."
        except ValueError as e:
            self.f_error.setText(str(e))
            self.f_error.show()
            return
        self.message.emit(msg)
        self.refresh(select_id=iid)

    # ---------- lista ----------
    def _fill_locations(self):
        keep = self.loc_box.currentData()
        with Session() as s:
            locs = stock.locations(s, self.profile.id)
        self.loc_box.blockSignals(True)
        self.loc_box.clear()
        self.loc_box.addItem("Todos os locais", None)
        for loc in locs:
            self.loc_box.addItem(loc.name, loc.id)
        self.loc_box.setCurrentIndex(max(0, self.loc_box.findData(keep)))
        self.loc_box.blockSignals(False)
        self.loc_box.setVisible(len(locs) > 1)

    def refresh(self, select_id: int | None = None):
        if select_id is None or isinstance(select_id, bool):
            select_id = self.current.id if self.current else None
        self._fill_locations()
        with Session() as s:
            items = stock.list_items(s, self.profile.id, self.search.text(), self.kind_box.currentData(),
                                     include_inactive=bool(self.search.text().strip()),
                                     location_id=self.loc_box.currentData())
        if self.low_only.isChecked():
            items = [i for i in items if i.below_min]
        self.items = items
        self.table.blockSignals(True)
        self.table.setRowCount(len(items))
        mono = theme.mono_font()
        sel_row = None
        for r, it in enumerate(items):
            cells = [it.code, it.name + ("" if it.is_active else " (inativo)"), it.kind_label, it.unit,
                     stock.fmt_qty(it.balance), stock.fmt_qty(it.min_stock) if it.min_stock is not None else "",
                     money.fmt(it.avg_cost.quantize(Decimal("0.01"))) if it.avg_cost else "",
                     money.fmt(it.value) if it.value else ""]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if COLS[c][2]:
                    item.setFont(mono)
                    item.setTextAlignment(R)
                if it.below_min and c in (1, 4):
                    from PySide6.QtGui import QBrush, QColor
                    item.setForeground(QBrush(QColor(self.t["neg"])))
                    item.setToolTip("Abaixo do estoque mínimo")
                self.table.setItem(r, c, item)
            if it.id == select_id:
                sel_row = r
        self.table.blockSignals(False)
        self.table.setVisible(bool(items))
        self.empty.setVisible(not items)
        self.empty.setText("Nenhum item cadastrado ainda. Clique em Novo item." if not self.search.text().strip()
                           and not self.low_only.isChecked() and self.kind_box.currentData() is None
                           else "Nenhum item com esses filtros.")
        total = sum((i.value for i in items), Decimal(0))
        low = sum(1 for i in items if i.below_min)
        self.footer.setText(f"{len(items)} {'item' if len(items) == 1 else 'itens'} &nbsp;·&nbsp; em estoque "
                            f"<b>{money.fmt(total)}</b> (pelo custo médio)"
                            + (f" &nbsp;·&nbsp; <span style='color:{self.t['neg']}'>{low} abaixo do mínimo</span>"
                               if low else ""))
        if sel_row is not None:
            self.table.selectRow(sel_row)
            self._picked()
        else:
            self.current = None
            self._show_detail()

    def _picked(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        self.current = self.items[min(rows)] if rows else None
        self._show_detail()

    # ---------- ações ----------
    def open_move(self, kind: str):
        from finora.ui.stock_dialogs import MoveDialog
        if not self.items and kind != "in":
            self.message.emit("Cadastre um item primeiro (Novo item).")
            return
        dlg = MoveDialog(self, self.profile.id, kind, self.t, self.current.id if self.current else None)
        if dlg.exec() and dlg.done_text:
            self.message.emit(dlg.done_text)
            self.refresh()

    def open_locations(self):
        from finora.ui.stock_dialogs import LocationsDialog
        dlg = LocationsDialog(self, self.profile.id, self.t)
        dlg.exec()
        if dlg.changed:
            self.refresh()

    def delete_move(self):
        from finora.ui.stock_dialogs import confirm_delete_move
        r = self.hist.currentRow()
        if not (0 <= r < len(self.moves)):
            self.message.emit("Escolha o movimento na lista de movimentos.")
            return
        m = self.moves[r]
        if not confirm_delete_move(self, m.entry_id):
            return
        try:
            with Session() as s:
                stock.delete_move(s, m.id)
        except ValueError as e:
            self.message.emit(str(e))
            return
        self.message.emit("Movimento excluído.")
        self.refresh()

    def export_sheet(self) -> export.Sheet:
        loc = self.loc_box.currentText() if self.loc_box.currentData() else "Todos os locais"
        sheet = export.Sheet("Estoque", loc, ["Código", "Item", "Tipo", "Unidade", "Saldo", "Mínimo",
                                               "Custo médio", "Em estoque"], currency=self.profile.currency)
        for it in self.items:
            sheet.add([it.code, it.name, it.kind_label, it.unit, stock.fmt_qty(it.balance),
                       stock.fmt_qty(it.min_stock) if it.min_stock is not None else "",
                       it.avg_cost.quantize(Decimal("0.01")) if it.avg_cost else None, it.value or None])
        total = sum((i.value for i in self.items), Decimal(0))
        sheet.footer = f"{len(self.items)} itens · em estoque {money.fmt(total, self.profile.currency)}"
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
