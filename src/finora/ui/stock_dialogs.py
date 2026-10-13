"""Janelas do Estoque: movimento (entrada, saída, perda, inventário, transferência) e locais."""
from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDateEdit, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, categories, contacts, stock
from finora.ui import theme
from finora.ui.widgets import button, field_label

TITLES = {"in": "Entrada no estoque", "out": "Saída / consumo", "loss": "Perda", "adjust": "Inventário",
          "transfer": "Transferir entre locais"}
HINTS = {"in": "Compra, doação recebida ou qualquer coisa que chegou. Com o custo, o Finora calcula o custo médio.",
         "out": "Uso interno ou consumo (material do escritório, insumo usado). Sai pelo custo médio.",
         "loss": "Quebra, vencimento, furto… Sai do estoque pelo custo médio e aparece como perda.",
         "adjust": "Conte o que tem de verdade e informe aqui: o Finora lança a diferença (sobra ou falta).",
         "transfer": "Leva o item de um local para outro. O saldo total não muda."}


def parse_qty(text: str) -> Decimal:
    t = (text or "").strip().replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        raise ValueError("Quantidade inválida.")


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class MoveDialog(QDialog):
    def __init__(self, parent, entity_id: int, kind: str, t: dict, item_id: int | None = None):
        super().__init__(parent)
        self.entity_id, self.kind, self.t = entity_id, kind, t
        self.done_text = ""
        self.setObjectName("wizard")
        self.setWindowTitle(TITLES[kind])
        self.setMinimumWidth(460)
        with Session() as s:
            self.items = stock.list_items(s, entity_id)
            self.locs = [(loc.id, loc.name) for loc in stock.locations(s, entity_id)]
            accs = [(a.id, a.name) for a in accounts.list_accounts(s, entity_id) if a.kind != "card"]
            cards_ = [(a.id, a.name) for a in accounts.list_accounts(s, entity_id) if a.kind == "card"]
            cats = categories.choices(s, entity_id, "expense")
            people = contacts.names(s, entity_id)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        hint = QLabel(HINTS[kind], wordWrap=True)
        hint.setProperty("role", "muted")
        lay.addWidget(hint)
        g = QGridLayout()
        g.setHorizontalSpacing(theme.SP_M)
        g.setVerticalSpacing(3)
        row = 0

        def put(label, w, col=0, span=1, help_text=None):
            nonlocal row
            g.addWidget(field_label(label, t, help_text), row, col, 1, span)
            g.addWidget(w, row + 1, col, 1, span)

        self.item = QComboBox()
        for it in self.items:
            self.item.addItem(f"{it.name} ({it.unit})" + (f" · {it.code}" if it.code else ""), it.id)
        self.item.setEditable(True)
        self.item.setInsertPolicy(QComboBox.NoInsert)
        self.item.completer().setFilterMode(Qt.MatchContains)
        self.item.completer().setCompletionMode(QCompleter.PopupCompletion)
        if item_id is not None:
            self.item.setCurrentIndex(max(0, self.item.findData(item_id)))
        put("Item", self.item, span=2)
        row += 2
        self.balance_lbl = QLabel()
        self.balance_lbl.setProperty("role", "field")
        g.addWidget(self.balance_lbl, row, 0, 1, 2)
        row += 1
        self.day = QDateEdit(_qdate(date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.qty = QLineEdit(placeholderText="0")
        self.qty.setFont(theme.mono_font())
        self.qty.setAlignment(Qt.AlignRight)
        put("Data", self.day, 0)
        put("Quantidade contada" if kind == "adjust" else "Quantidade", self.qty, 1)
        row += 2
        self.loc = QComboBox()
        self.loc_to = QComboBox()
        for lid, name in self.locs:
            self.loc.addItem(name, lid)
            self.loc_to.addItem(name, lid)
        if kind == "transfer":
            put("De", self.loc, 0)
            put("Para", self.loc_to, 1)
            self.loc_to.setCurrentIndex(min(1, self.loc_to.count() - 1))
            row += 2
        elif len(self.locs) > 1:
            put("Local", self.loc, 0, 2)
            row += 2

        # entrada: custo, fornecedor, documento e a compra em contas a pagar
        self.cost = QLineEdit(placeholderText="0,00")
        self.cost.setFont(theme.mono_font())
        self.cost.setAlignment(Qt.AlignRight)
        self.total_lbl = QLabel()
        self.total_lbl.setProperty("role", "field")
        self.contact = QComboBox(editable=True)
        self.contact.addItem("")
        self.contact.addItems(people)
        self.contact.setInsertPolicy(QComboBox.NoInsert)
        self.contact.lineEdit().setPlaceholderText("Opcional")
        self.doc = QLineEdit(maxLength=40, placeholderText="Nº da nota (opcional)")
        self.payable = QCheckBox("Lançar a compra em Contas a pagar")
        self.pay_acc = QComboBox()
        for aid, name in accs + cards_:
            self.pay_acc.addItem(name, aid)
        self.pay_due = QDateEdit(_qdate(date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.pay_paid = QCheckBox("Já foi paga")
        self.pay_cat = QComboBox()
        self.pay_cat.addItem("Categoria do item", None)
        for cid, label in cats:
            self.pay_cat.addItem(label, cid)
        self.pay_box = QWidget()
        pb = QGridLayout(self.pay_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setHorizontalSpacing(theme.SP_M)
        pb.setVerticalSpacing(3)
        pb.addWidget(field_label("Pagar pela conta", t), 0, 0)
        pb.addWidget(self.pay_acc, 1, 0)
        pb.addWidget(field_label("Vencimento", t), 0, 1)
        pb.addWidget(self.pay_due, 1, 1)
        pb.addWidget(field_label("Categoria", t), 2, 0, 1, 2)
        pb.addWidget(self.pay_cat, 3, 0, 1, 2)
        pb.addWidget(self.pay_paid, 4, 0, 1, 2)
        if kind == "in":
            put("Custo unitário", self.cost, 0, help_text="Quanto custou cada unidade. Doação: deixe 0.")
            g.addWidget(self.total_lbl, row + 1, 1)
            row += 2
            put("Fornecedor", self.contact, 0)
            put("Documento", self.doc, 1)
            row += 2
            g.addWidget(self.payable, row, 0, 1, 2)
            row += 1
            g.addWidget(self.pay_box, row, 0, 1, 2)
            row += 1
            self.payable.setChecked(bool(accs or cards_))
            self.payable.setEnabled(bool(accs or cards_))
        self.notes = QLineEdit(maxLength=300, placeholderText={"out": "Ex.: uso no escritório, envase do lote 12",
                                                               "loss": "Ex.: garrafas quebradas no transporte",
                                                               "adjust": "Ex.: contagem de fim de mês"}.get(kind, ""))
        put("Observação", self.notes, 0, 2)
        row += 2
        lay.addLayout(g)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancelar", "secondary")
        self.ok = button("Salvar", "primary")
        self.ok.setDefault(True)
        btns.addWidget(cancel)
        btns.addWidget(self.ok)
        lay.addLayout(btns)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.save)
        self.item.currentIndexChanged.connect(self._update)
        self.loc.currentIndexChanged.connect(self._update)
        self.qty.textChanged.connect(self._update)
        self.cost.textChanged.connect(self._update)
        self.payable.toggled.connect(self.pay_box.setVisible)
        self.pay_box.setVisible(kind == "in" and self.payable.isChecked())
        self._update()
        self.qty.setFocus()

    def _current(self):
        iid = self.item.currentData()
        return next((i for i in self.items if i.id == iid), None)

    def _update(self):
        it = self._current()
        if it is None:
            self.balance_lbl.setText("Cadastre o item primeiro (botão Novo item).")
            return
        with Session() as s:
            here = stock.balance(s, self.entity_id, it.id, self.loc.currentData() if len(self.locs) > 1 else None)
        text = f"Saldo agora: {stock.fmt_qty(here, it.unit)}"
        if it.avg_cost:
            text += f" · custo médio {money.fmt(it.avg_cost.quantize(Decimal('0.01')))}"
        if self.kind == "adjust":
            try:
                diff = parse_qty(self.qty.text()) - here if self.qty.text().strip() else None
            except ValueError:
                diff = None
            if diff:
                text += f" · diferença: {'+' if diff > 0 else ''}{stock.fmt_qty(diff, it.unit)}"
        self.balance_lbl.setText(text)
        if self.kind == "in":
            try:
                total = parse_qty(self.qty.text()) * money.parse(self.cost.text())
                self.total_lbl.setText(f"Total: {money.fmt(total.quantize(Decimal('0.01')))}")
            except (ValueError, InvalidOperation):
                self.total_lbl.clear()

    def _err(self, text: str):
        self.error.setText(text)
        self.error.show()

    def save(self):
        it = self._current()
        if it is None:
            self._err("Escolha o item.")
            return
        day = self.day.date().toPython()
        loc = self.loc.currentData() if (len(self.locs) > 1 or self.kind == "transfer") else None
        try:
            q = parse_qty(self.qty.text())
            with Session() as s:
                if self.kind == "adjust":
                    stock.adjust(s, self.entity_id, item_id=it.id, counted=q, day=day, location_id=loc,
                                 notes=self.notes.text())
                elif self.kind == "transfer":
                    stock.transfer(s, self.entity_id, item_id=it.id, quantity=q, day=day, from_id=loc,
                                   to_id=self.loc_to.currentData(), notes=self.notes.text())
                else:
                    cost = money.parse(self.cost.text()) if self.kind == "in" else None
                    payable = None
                    if self.kind == "in" and self.payable.isChecked():
                        payable = {"account_id": self.pay_acc.currentData(),
                                   "due_date": self.pay_due.date().toPython(),
                                   "category_id": self.pay_cat.currentData(), "paid": self.pay_paid.isChecked()}
                    stock.move(s, self.entity_id, item_id=it.id, kind=self.kind, quantity=q, day=day,
                               location_id=loc, unit_cost=cost, contact=self.contact.currentText(),
                               document_no=self.doc.text(), notes=self.notes.text(), payable=payable)
        except ValueError as e:
            self._err(str(e))
            return
        self.done_text = f"{TITLES[self.kind]}: {it.name}, {stock.fmt_qty(q, it.unit)}."
        if self.kind == "in" and self.payable.isChecked() and money.parse(self.cost.text() or "0") > 0:
            self.done_text += " A compra foi para Contas a pagar."
        self.accept()


class LocationsDialog(QDialog):
    """Locais de estoque: criar, renomear e inativar."""

    def __init__(self, parent, entity_id: int, t: dict):
        super().__init__(parent)
        self.entity_id = entity_id
        self.changed = False
        self.setObjectName("wizard")
        self.setWindowTitle("Locais de estoque")
        self.setMinimumSize(420, 360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        intro = QLabel("Onde os itens ficam: depósito, galpão, almoxarifado, apiário… Com um local só, o Finora nem "
                       "pergunta.", wordWrap=True)
        intro.setProperty("role", "muted")
        lay.addWidget(intro)
        self.list = QListWidget(objectName="contactList")
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.name = QLineEdit(maxLength=80, placeholderText="Nome do local")
        add = button("Adicionar", "secondary", t, "fa6s.plus", "fg")
        self.rename = button("Renomear", "link")
        self.toggle = button("Inativar", "link")
        row.addWidget(self.name, 1)
        row.addWidget(add)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(self.rename)
        row2.addWidget(self.toggle)
        row2.addStretch(1)
        close = button("Fechar", "secondary")
        row2.addWidget(close)
        lay.addLayout(row2)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        add.clicked.connect(self.add)
        self.rename.clicked.connect(self.do_rename)
        self.toggle.clicked.connect(self.do_toggle)
        close.clicked.connect(self.accept)
        self.list.currentRowChanged.connect(self._picked)
        self.refresh()

    def refresh(self):
        with Session() as s:
            self.locs = stock.locations(s, self.entity_id, include_inactive=True)
        self.list.clear()
        for loc in self.locs:
            it = QListWidgetItem(loc.name + ("" if loc.is_active else "  (inativo)"))
            it.setData(Qt.UserRole, loc.id)
            self.list.addItem(it)

    def _picked(self, row: int):
        if 0 <= row < len(self.locs):
            loc = self.locs[row]
            self.name.setText(loc.name)
            self.toggle.setText("Inativar" if loc.is_active else "Reativar")

    def _run(self, fn):
        try:
            with Session() as s:
                fn(s)
        except ValueError as e:
            self.error.setText(str(e))
            self.error.show()
            return False
        self.error.hide()
        self.changed = True
        self.refresh()
        return True

    def add(self):
        if self._run(lambda s: stock.save_location(s, self.entity_id, self.name.text())):
            self.name.clear()

    def _sel(self):
        r = self.list.currentRow()
        return self.locs[r] if 0 <= r < len(self.locs) else None

    def do_rename(self):
        loc = self._sel()
        if loc is not None:
            self._run(lambda s: stock.save_location(s, self.entity_id, self.name.text(), loc.id, loc.is_active))

    def do_toggle(self):
        loc = self._sel()
        if loc is not None:
            self._run(lambda s: stock.save_location(s, self.entity_id, loc.name, loc.id, not loc.is_active))


def confirm_delete_move(parent, entry_id: int | None) -> bool:
    text = "Excluir este movimento? O saldo e o custo médio são recalculados."
    if entry_id:
        text += "\n\nO lançamento da compra em Contas a pagar continua lá; exclua-o em Lançamentos se precisar."
    return QMessageBox.question(parent, "Excluir movimento", text,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
