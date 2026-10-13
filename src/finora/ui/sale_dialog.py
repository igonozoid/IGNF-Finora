"""Janela do pedido de venda: cliente, itens, desconto/frete, pagamento; salvar orçamento ou confirmar."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDateEdit, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, categories, contacts, export, sales, stock
from finora.services.sales import SaleData, SaleLine
from finora.ui import theme
from finora.ui.stock_dialogs import parse_qty
from finora.ui.widgets import button, field_label

R = Qt.AlignRight | Qt.AlignVCenter


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class SaleDialog(QDialog):
    def __init__(self, parent, entity_id: int, currency: str, t: dict, sale_id: int | None = None):
        super().__init__(parent)
        self.entity_id, self.currency, self.t = entity_id, currency, t
        self.sale_id = sale_id
        self.done_text = ""
        self.lines: list[SaleLine] = []
        self.setObjectName("wizard")
        self.resize(900, 640)
        self.setMinimumSize(720, 520)
        with Session() as s:
            self.items = {i.id: i for i in stock.list_items(s, entity_id)}
            self.sellable = [i for i in self.items.values() if i.kind in ("product", "produced")] or \
                list(self.items.values())
            accs = [(a.id, a.name) for a in accounts.list_accounts(s, entity_id)]
            cats = categories.choices(s, entity_id, "income")
            people = contacts.names(s, entity_id)
            self.locs = [(loc.id, loc.name) for loc in stock.locations(s, entity_id)]
            self.detail = sales.get(s, sale_id) if sale_id else None
            if self.detail:
                for iid in self.detail.data.lines:
                    if iid.item_id not in self.items:          # item inativado depois: ainda aparece no pedido
                        self.items[iid.item_id] = stock.get_item(s, iid.item_id)
        self.readonly = bool(self.detail and self.detail.status != "quote")
        title = f"Pedido nº {self.detail.number}" if self.detail else "Novo pedido"
        if self.detail:
            title += f" — {sales.STATUS[self.detail.status]}"
        self.setWindowTitle(title)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        head = QGridLayout()
        head.setHorizontalSpacing(theme.SP_M)
        head.setVerticalSpacing(3)
        self.contact = QComboBox(editable=True)
        self.contact.addItem("")
        self.contact.addItems(people)
        self.contact.setInsertPolicy(QComboBox.NoInsert)
        self.contact.lineEdit().setPlaceholderText("Nome do cliente")
        self.day = QDateEdit(_qdate(date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.kind = QComboBox()
        for k, label in sales.KINDS.items():
            self.kind.addItem(label, k)
        for col, (label, w) in enumerate((("Cliente", self.contact), ("Data", self.day), ("Tipo", self.kind))):
            head.addWidget(field_label(label, t), 0, col)
            head.addWidget(w, 1, col)
        head.setColumnStretch(0, 3)
        lay.addLayout(head)

        # linha para incluir item
        add_row = QHBoxLayout()
        add_row.setSpacing(theme.SP_S)
        self.pick = QComboBox(editable=True)
        for it in self.sellable:
            self.pick.addItem(f"{it.name} ({it.unit})" + (f" · {it.code}" if it.code else ""), it.id)
        self.pick.setInsertPolicy(QComboBox.NoInsert)
        self.pick.completer().setFilterMode(Qt.MatchContains)
        self.pick.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.p_qty = QLineEdit("1")
        self.p_price = QLineEdit()
        for w in (self.p_qty, self.p_price):
            w.setFont(theme.mono_font())
            w.setAlignment(Qt.AlignRight)
            w.setMaximumWidth(100)
        self.p_add = button("Incluir", "secondary", t, "fa6s.plus", "fg")
        self.p_hint = QLabel()
        self.p_hint.setProperty("role", "field")
        add_row.addWidget(self.pick, 1)
        add_row.addWidget(QLabel("Qtd."))
        add_row.addWidget(self.p_qty)
        add_row.addWidget(QLabel("Preço"))
        add_row.addWidget(self.p_price)
        add_row.addWidget(self.p_add)
        self.add_box = QFrame()
        ab = QVBoxLayout(self.add_box)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(2)
        ab.addLayout(add_row)
        ab.addWidget(self.p_hint)
        lay.addWidget(self.add_box)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ITEM", "QTD.", "PREÇO", "TOTAL", "MARGEM"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 90), (2, 110), (3, 120), (4, 90)):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
            hdr.resizeSection(c, w)
            self.table.horizontalHeaderItem(c).setTextAlignment(R)
        lay.addWidget(self.table, 1)
        self.remove_line = button("Remover item selecionado", "link", t, "fa6s.xmark")
        lay.addWidget(self.remove_line, 0, Qt.AlignLeft)

        # totais e pagamento
        bottom = QHBoxLayout()
        bottom.setSpacing(theme.SP_L)
        pay = QGridLayout()
        pay.setHorizontalSpacing(theme.SP_M)
        pay.setVerticalSpacing(3)
        self.account = QComboBox()
        for aid, name in accs:
            self.account.addItem(name, aid)
        self.payment = QComboBox()
        self.payment.addItems(sales.PAYMENTS)
        self.parts = QSpinBox(minimum=1, maximum=60, value=1)
        self.parts.setSuffix("x")
        self.first_due = QDateEdit(_qdate(date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.paid_now = QCheckBox("Já recebido (à vista)")
        self.category = QComboBox()
        self.category.addItem("Automática (do item)", None)
        for cid, label in cats:
            self.category.addItem(label, cid)
        self.loc = QComboBox()
        for lid, name in self.locs:
            self.loc.addItem(name, lid)
        self.pay_widgets = []
        for i, (label, w) in enumerate((("Receber na conta", self.account), ("Forma", self.payment),
                                        ("Parcelas", self.parts), ("1º vencimento", self.first_due))):
            lbl = field_label(label, t)
            pay.addWidget(lbl, 0, i)
            pay.addWidget(w, 1, i)
            self.pay_widgets += [lbl, w]
        cat_lbl = field_label("Categoria", t)
        pay.addWidget(cat_lbl, 2, 0, 1, 2)
        pay.addWidget(self.category, 3, 0, 1, 2)
        pay.addWidget(self.paid_now, 3, 2, 1, 2)
        self.pay_widgets += [cat_lbl, self.category, self.paid_now]
        if len(self.locs) > 1:
            pay.addWidget(field_label("Sai do local", t), 4, 0, 1, 2)
            pay.addWidget(self.loc, 5, 0, 1, 2)
        self.notes = QLineEdit(maxLength=300, placeholderText="Observação (opcional)")
        pay.addWidget(self.notes, 6, 0, 1, 4)
        bottom.addLayout(pay, 3)
        tot = QGridLayout()
        tot.setVerticalSpacing(3)
        self.discount = QLineEdit(placeholderText="0,00")
        self.freight = QLineEdit(placeholderText="0,00")
        for w in (self.discount, self.freight):
            w.setFont(theme.mono_font())
            w.setAlignment(Qt.AlignRight)
            w.setMaximumWidth(120)
        self.sub_lbl = QLabel()
        self.total_lbl = QLabel()
        for w in (self.sub_lbl, self.total_lbl):
            w.setFont(theme.mono_font())
            w.setAlignment(R)
        f = self.total_lbl.font()
        f.setPointSize(13)
        f.setBold(True)
        self.total_lbl.setFont(f)
        tot.addWidget(QLabel("Itens"), 0, 0)
        tot.addWidget(self.sub_lbl, 0, 1)
        tot.addWidget(QLabel("(−) Desconto"), 1, 0)
        tot.addWidget(self.discount, 1, 1, Qt.AlignRight)
        tot.addWidget(QLabel("(+) Frete"), 2, 0)
        tot.addWidget(self.freight, 2, 1, Qt.AlignRight)
        tot.addWidget(QLabel("Total"), 3, 0)
        tot.addWidget(self.total_lbl, 3, 1)
        self.parts_lbl = QLabel()
        self.parts_lbl.setProperty("role", "field")
        tot.addWidget(self.parts_lbl, 4, 0, 1, 2)
        bottom.addLayout(tot, 2)
        lay.addLayout(bottom)

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        self.print_btn = button("Imprimir pedido", "link", t, "fa6s.print")
        self.cancel_sale = button("Cancelar pedido", "link", t, "fa6s.ban")
        btns.addWidget(self.print_btn)
        btns.addWidget(self.cancel_sale)
        btns.addStretch(1)
        close = button("Fechar", "secondary")
        self.save_btn = button("Salvar orçamento", "secondary")
        self.confirm_btn = button("Confirmar venda", "primary", t, "fa6s.check", "on_acc")
        for w in (close, self.save_btn, self.confirm_btn):
            btns.addWidget(w)
        lay.addLayout(btns)

        close.clicked.connect(self.reject)
        self.save_btn.clicked.connect(lambda: self.save(confirm=False))
        self.confirm_btn.clicked.connect(lambda: self.save(confirm=True))
        self.print_btn.clicked.connect(self.print_order)
        self.cancel_sale.clicked.connect(self.do_cancel)
        self.p_add.clicked.connect(self.add_line)
        self.p_price.returnPressed.connect(self.add_line)
        self.p_qty.returnPressed.connect(self.add_line)
        self.pick.currentIndexChanged.connect(self._picked)
        self.remove_line.clicked.connect(self.del_line)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        for w in (self.discount, self.freight):
            w.textChanged.connect(self._totals)
        self.parts.valueChanged.connect(self._totals)
        self.paid_now.toggled.connect(self._totals)
        self._load()
        self._picked()
        self._kind_changed()

    # ----- carregar -----
    def _load(self):
        d = self.detail.data if self.detail else None
        if d:
            self.contact.setCurrentText(d.contact)
            self.day.setDate(_qdate(d.day))
            self.kind.setCurrentIndex(max(0, self.kind.findData(d.kind)))
            self.lines = list(d.lines)
            self.discount.setText(money.fmt(d.discount).split(" ", 1)[-1] if d.discount else "")
            self.freight.setText(money.fmt(d.freight).split(" ", 1)[-1] if d.freight else "")
            if d.account_id:
                self.account.setCurrentIndex(max(0, self.account.findData(d.account_id)))
            if d.payment:
                self.payment.setCurrentText(d.payment)
            self.parts.setValue(d.installments or 1)
            self.first_due.setDate(_qdate(d.first_due or d.day))
            self.paid_now.setChecked(d.paid_now)
            self.category.setCurrentIndex(max(0, self.category.findData(d.category_id)))
            if d.location_id:
                self.loc.setCurrentIndex(max(0, self.loc.findData(d.location_id)))
            self.notes.setText(d.notes)
        self._fill()
        ro = self.readonly
        for w in (self.contact, self.day, self.kind, self.discount, self.freight, self.account, self.payment,
                  self.parts, self.first_due, self.paid_now, self.category, self.loc, self.notes):
            w.setEnabled(not ro)
        self.add_box.setVisible(not ro)
        self.remove_line.setVisible(not ro)
        self.save_btn.setVisible(not ro)
        self.confirm_btn.setVisible(not ro)
        self.cancel_sale.setVisible(bool(self.detail) and self.detail.status != "canceled")
        self.print_btn.setVisible(bool(self.detail))

    def _picked(self):
        it = self.items.get(self.pick.currentData())
        if it is None:
            self.p_hint.setText("Cadastre os produtos em Estoque (Novo item).")
            return
        self.p_price.setText(money.fmt(it.sale_price).split(" ", 1)[-1] if it.sale_price else "")
        self.p_hint.setText(f"Em estoque: {stock.fmt_qty(it.balance, it.unit)}"
                            + (f" · custo médio {money.fmt(it.avg_cost.quantize(Decimal('0.01')))}"
                               if it.avg_cost else ""))

    def _kind_changed(self):
        is_sale = self.kind.currentData() == "sale"
        for w in self.pay_widgets:
            w.setVisible(is_sale)
        self.confirm_btn.setText({"sale": "Confirmar venda", "donation": "Confirmar doação",
                                  "bonus": "Confirmar bonificação"}[self.kind.currentData()])
        self._totals()

    # ----- itens -----
    def add_line(self):
        it = self.items.get(self.pick.currentData())
        if it is None:
            return
        try:
            q = parse_qty(self.p_qty.text())
            price = money.parse(self.p_price.text() or "0")
            if q <= 0:
                raise ValueError("Quantidade precisa ser maior que zero.")
        except ValueError as e:
            self._err(str(e))
            return
        self.error.hide()
        self.lines.append(SaleLine(it.id, q, price))
        self.p_qty.setText("1")
        self._fill()
        self.pick.setFocus()

    def del_line(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.lines):
            del self.lines[r]
            self._fill()

    def _fill(self):
        self.table.setRowCount(len(self.lines))
        mono = theme.mono_font()
        costs = self.detail.costs if self.detail else {}
        for r, ln in enumerate(self.lines):
            it = self.items.get(ln.item_id)
            line_total = (Decimal(ln.quantity) * Decimal(ln.unit_price)).quantize(Decimal("0.01"))
            cost = costs.get(r, it.avg_cost if it else Decimal(0))
            margin = ((line_total - Decimal(ln.quantity) * cost) * 100 / line_total).quantize(Decimal("1")) \
                if line_total and cost else None
            cells = [f"{it.name if it else '?'}", stock.fmt_qty(ln.quantity, it.unit if it else ""),
                     money.fmt(ln.unit_price, self.currency), money.fmt(line_total, self.currency),
                     f"{margin}%" if margin is not None else ""]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c:
                    item.setFont(mono)
                    item.setTextAlignment(R)
                if c == 4:
                    item.setToolTip("Margem bruta: (preço − custo médio) ÷ preço")
                self.table.setItem(r, c, item)
        self._totals()

    def _parse(self, w: QLineEdit) -> Decimal:
        try:
            return money.parse(w.text() or "0")
        except ValueError:
            return Decimal(0)

    def _totals(self):
        sub = sales.subtotal(self.lines)
        is_sale = self.kind.currentData() == "sale"
        total = sales.total_of(self.lines, self._parse(self.discount), self._parse(self.freight)) if is_sale else sub
        self.sub_lbl.setText(money.fmt(sub, self.currency))
        self.total_lbl.setText(money.fmt(total, self.currency) if is_sale else "sem cobrança")
        n = self.parts.value()
        self.first_due.setEnabled(not self.readonly and not self.paid_now.isChecked())
        self.parts.setEnabled(not self.readonly and not self.paid_now.isChecked())
        if is_sale and n > 1 and total > 0:
            self.parts_lbl.setText(f"{n}x de {money.fmt(total / n, self.currency)} (aprox.)")
        else:
            self.parts_lbl.setText("")

    # ----- gravar -----
    def _err(self, text: str):
        self.error.setText(text)
        self.error.show()

    def _data(self) -> SaleData:
        is_sale = self.kind.currentData() == "sale"
        paid = is_sale and self.paid_now.isChecked()
        return SaleData(day=self.day.date().toPython(), lines=list(self.lines), contact=self.contact.currentText(),
                        kind=self.kind.currentData(), discount=self._parse(self.discount) if is_sale else Decimal(0),
                        freight=self._parse(self.freight) if is_sale else Decimal(0),
                        account_id=self.account.currentData() if is_sale else None,
                        payment=self.payment.currentText() if is_sale else None,
                        installments=1 if paid else self.parts.value(),
                        first_due=self.day.date().toPython() if paid else self.first_due.date().toPython(),
                        paid_now=paid, location_id=self.loc.currentData() if len(self.locs) > 1 else None,
                        category_id=self.category.currentData() if is_sale else None, notes=self.notes.text())

    def save(self, confirm: bool):
        try:
            with Session() as s:
                self.sale_id = sales.save(s, self.entity_id, self._data(), self.sale_id)
                number = s.get(sales.Sale, self.sale_id).number
                if confirm:
                    n = sales.confirm(s, self.sale_id)
        except ValueError as e:
            self._err(str(e))
            return
        if confirm:
            kind = sales.KINDS[self.kind.currentData()].lower()
            self.done_text = f"Pedido {number} confirmado ({kind}): estoque baixado" + (
                f", {n} {'parcela' if n == 1 else 'parcelas'} em Contas a receber." if n else ".")
        else:
            self.done_text = f"Orçamento {number} salvo."
        self.accept()

    def do_cancel(self):
        if self.detail is None:
            return
        if QMessageBox.question(self, "Cancelar pedido",
                                f"Cancelar o pedido nº {self.detail.number}?\n\nSe estava confirmado, os itens voltam "
                                "ao estoque e as parcelas a receber vão para a lixeira.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            with Session() as s:
                sales.cancel(s, self.detail.id)
        except ValueError as e:
            self._err(str(e))
            return
        self.done_text = f"Pedido {self.detail.number} cancelado."
        self.accept()

    def order_sheet(self) -> export.Sheet:
        d = self.detail
        who = d.data.contact or "sem cliente"
        sheet = export.Sheet(f"{sales.KINDS[d.data.kind]} — pedido nº {d.number}",
                             f"{who} · {d.data.day:%d/%m/%Y} · {sales.STATUS[d.status]}",
                             ["Item", "Quantidade", "Preço", "Total"], currency=self.currency)
        for ln in d.data.lines:
            name, unit = d.names.get(ln.item_id, ("?", ""))
            sheet.add([name, stock.fmt_qty(ln.quantity, unit), Decimal(ln.unit_price),
                       (Decimal(ln.quantity) * Decimal(ln.unit_price)).quantize(Decimal("0.01"))])
        if d.data.discount:
            sheet.add(["Desconto", "", None, -d.data.discount], "detail")
        if d.data.freight:
            sheet.add(["Frete", "", None, d.data.freight], "detail")
        sheet.add(["Total", "", None, d.total], "bold")
        parts = " · ".join(f"{due:%d/%m/%Y} {money.fmt(v, self.currency)}" + (" (recebida)" if paid else "")
                           for due, v, paid in d.installments)
        foot = [f"Pagamento: {d.data.payment}" if d.data.payment else "", f"Parcelas: {parts}" if parts else "",
                d.data.notes]
        sheet.footer = " · ".join(x for x in foot if x)
        return sheet

    def print_order(self):
        from finora.ui import printing
        printing.open_print(self, self.order_sheet(), self.t)
