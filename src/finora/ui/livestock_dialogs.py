"""Janelas da Pecuária: lote de animais e registro do lote (nascimento, compra, venda, pesagem, sanidade…)."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QSpinBox,
    QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, contacts, livestock, rural, stock
from finora.services.livestock import EventData, Use
from finora.ui import theme
from finora.ui.production_dialog import LinesBox
from finora.ui.rural_dialogs import _Form
from finora.ui.widgets import button, field_label, help_icon

WITH_HEADS = {"birth", "purchase", "sale", "death", "transfer", "weighing"}
WITH_WEIGHT = {"birth", "purchase", "sale", "weighing"}
WITH_MONEY = {"purchase", "sale"}
WITH_INPUTS = {"health", "feeding", "occurrence"}


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _fmt(v) -> str:
    return money.fmt(v).split(" ", 1)[-1] if v else ""


class LotDialog(_Form):
    def __init__(self, parent, entity_id: int, lot: livestock.LotView | None = None):
        super().__init__(parent, "Editar lote" if lot else "Novo lote de animais")
        self.entity_id, self.lot = entity_id, lot
        with Session() as s:
            area_list = rural.areas(s, entity_id)
        self.name = QLineEdit(maxLength=80, placeholderText="Ex.: Vacas de cria, Recria 2026")
        self.species = QComboBox()
        for k, label in livestock.SPECIES.items():
            self.species.addItem(label, k)
        self.category = QComboBox(editable=True)
        self.category.addItem("")
        self.category.addItems(livestock.CATEGORIES)
        self.area = QComboBox()
        self.area.addItem("—", None)
        for a in sorted(area_list, key=lambda a: (a.kind != "pasture", a.label.lower())):
            self.area.addItem(a.label, a.id)
        self.notes = QLineEdit(maxLength=300, placeholderText="Opcional")
        self.active = QCheckBox("Ativo")
        self.active.setChecked(True)
        for label, w in (("Nome", self.name), ("Espécie", self.species), ("Categoria", self.category),
                         ("Piquete inicial" if not lot else "Piquete de origem", self.area), ("Observação", self.notes),
                         ("", self.active)):
            self.form.addRow(label, w)
        if lot:
            self.name.setText(lot.name)
            self.species.setCurrentIndex(max(0, self.species.findData(lot.species)))
            self.category.setCurrentText(lot.category)
            self.notes.setText(lot.notes)
            self.active.setChecked(lot.is_active)
            with Session() as s:
                from finora.models import HerdLot
                self.area.setCurrentIndex(max(0, self.area.findData(s.get(HerdLot, lot.id).area_id)))

    def save(self) -> int:
        with Session() as s:
            return livestock.save_lot(s, self.entity_id, name=self.name.text(), species=self.species.currentData(),
                                      category=self.category.currentText(), area_id=self.area.currentData(),
                                      notes=self.notes.text(), is_active=self.active.isChecked(),
                                      lot_id=self.lot.id if self.lot else None)


class EventDialog(QDialog):
    def __init__(self, parent, entity_id: int, currency: str, t: dict, event_id: int | None = None,
                 lot_id: int | None = None):
        super().__init__(parent)
        self.entity_id, self.currency, self.t = entity_id, currency, t
        self.event_id = event_id
        self.done_text = ""
        self.setObjectName("wizard")
        self.resize(860, 640)
        self.setMinimumSize(700, 480)
        with Session() as s:
            items = stock.list_items(s, entity_id)
            self.lot_list = livestock.lots(s, entity_id, include_inactive=bool(event_id))
            area_list = rural.areas(s, entity_id)
            accs = [(a.id, a.name) for a in accounts.list_accounts(s, entity_id)]
            people = contacts.names(s, entity_id)
            self.locs = [(loc.id, loc.name) for loc in stock.locations(s, entity_id)]
            self.detail = livestock.get_event(s, event_id) if event_id else None
        order = {"input": 0, "material": 1, "product": 2, "produced": 3}
        ins = sorted(items, key=lambda i: (order.get(i.kind, 9), i.name.lower()))
        self.setWindowTitle(f"{self.detail.view.lot} — {self.detail.view.kind_label}" if self.detail
                            else "Novo registro do rebanho")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP_M)
        grid.setVerticalSpacing(3)
        self.lot = QComboBox()
        for lv in self.lot_list:
            self.lot.addItem(f"{lv.name} ({lv.heads} cab.)", lv.id)
        self.day = QDateEdit(_qdate(date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.kind = QComboBox()
        for k, label in livestock.EVENTS.items():
            self.kind.addItem(label, k)
        for col, (label, w) in enumerate((("Lote", self.lot), ("Data", self.day), ("Registro", self.kind))):
            grid.addWidget(field_label(label, t), 0, col)
            grid.addWidget(w, 1, col)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(2, 2)
        lay.addLayout(grid)

        # campos que dependem do tipo
        f = QGridLayout()
        f.setHorizontalSpacing(theme.SP_M)
        f.setVerticalSpacing(3)
        self.heads = QSpinBox(maximum=1_000_000)
        self.weight = QLineEdit(placeholderText="kg por cabeça")
        self.value = QLineEdit(placeholderText="0,00")
        for w in (self.weight, self.value):
            w.setFont(theme.mono_font())
            w.setAlignment(Qt.AlignRight)
        self.contact = QComboBox(editable=True)
        self.contact.addItem("")
        self.contact.addItems(people)
        self.contact.setInsertPolicy(QComboBox.NoInsert)
        self.area = QComboBox()
        for a in sorted(area_list, key=lambda a: (a.kind != "pasture", a.label.lower())):
            self.area.addItem(a.label, a.id)
        self.to_lot = QComboBox()
        for lv in self.lot_list:
            self.to_lot.addItem(lv.name, lv.id)
        self.fields: dict[str, list[QWidget]] = {}

        def put(key, row, col, label, w, span=1):
            lbl = field_label(label, t)
            f.addWidget(lbl, row, col, 1, span)
            f.addWidget(w, row + 1, col, 1, span)
            self.fields[key] = [lbl, w]
        put("heads", 0, 0, "Cabeças", self.heads)
        put("weight", 0, 1, "Peso médio (kg/cab.)", self.weight)
        put("value", 0, 2, "Valor total", self.value)
        put("contact", 0, 3, "Fornecedor / comprador", self.contact)
        put("area", 2, 0, "Para o piquete", self.area, 2)
        put("to_lot", 2, 2, "Para o lote", self.to_lot, 2)
        f.setColumnStretch(3, 2)
        lay.addLayout(f)

        # conta a pagar/receber
        self.fin_box = QWidget()
        fb = QGridLayout(self.fin_box)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.setHorizontalSpacing(theme.SP_M)
        fb.setVerticalSpacing(3)
        self.fin = QCheckBox()
        self.fin.setChecked(True)
        self.fin_acc = QComboBox()
        for aid, name in accs:
            self.fin_acc.addItem(name, aid)
        self.fin_due = QDateEdit(_qdate(date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.fin_paid = QCheckBox()
        self.fin_cat = QComboBox()
        fb.addWidget(self.fin, 0, 0, 1, 4)
        for col, (label, w) in enumerate((("Conta", self.fin_acc), ("Vencimento", self.fin_due),
                                          ("Categoria", self.fin_cat))):
            fb.addWidget(field_label(label, t), 1, col)
            fb.addWidget(w, 2, col)
        fb.addWidget(self.fin_paid, 2, 3)
        fb.setColumnStretch(2, 2)
        lay.addWidget(self.fin_box)

        self.inputs = LinesBox("Insumos usados (saem do estoque)", ins, t, False, self._changed)
        lay.addWidget(self.inputs, 1)
        self.filler = QWidget()                      # sem a lista de insumos, o espaço sobra aqui (e não nos rótulos)
        lay.addWidget(self.filler, 1)

        bottom = QGridLayout()
        bottom.setHorizontalSpacing(theme.SP_M)
        bottom.setVerticalSpacing(3)
        self.other = QLineEdit(placeholderText="0,00")
        self.other.setFont(theme.mono_font())
        self.other.setAlignment(Qt.AlignRight)
        self.other.setMaximumWidth(140)
        other_lbl = QHBoxLayout()
        other_lbl.addWidget(field_label("Outros custos", t))
        other_lbl.addWidget(help_icon("Veterinário, frete, mão de obra… o que não sai do estoque. Entra só no custo do\n"
                                      "lote; os pagamentos continuam em Lançamentos.", t))
        other_lbl.addStretch(1)
        self.desc = QLineEdit(maxLength=200, placeholderText="Descrição (ex.: Aftosa 1ª dose, causa da morte)")
        bottom.addLayout(other_lbl, 0, 0)
        bottom.addWidget(self.other, 1, 0)
        bottom.addWidget(field_label("Descrição", t), 0, 1)
        bottom.addWidget(self.desc, 1, 1)
        self.cost_lbl = QLabel()
        self.cost_lbl.setFont(theme.mono_font())
        self.cost_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.cost_lbl, 1, 2)
        bottom.setColumnStretch(1, 3)
        bottom.setColumnStretch(2, 1)
        lay.addLayout(bottom)

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        self.delete_btn = button("Excluir registro", "link", t, "fa6s.trash")
        btns.addWidget(self.delete_btn)
        btns.addStretch(1)
        close = button("Fechar", "secondary")
        self.save_btn = button("Salvar", "primary", t, "fa6s.check", "on_acc")
        btns.addWidget(close)
        btns.addWidget(self.save_btn)
        lay.addLayout(btns)

        close.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self.save)
        self.delete_btn.clicked.connect(self.do_delete)
        self.kind.currentIndexChanged.connect(lambda _i: self._kind_changed())
        self.fin.toggled.connect(lambda _on: self._kind_changed())
        self.fin_paid.toggled.connect(lambda on: self.fin_due.setEnabled(not on))
        self.day.dateChanged.connect(lambda _d: self._changed())
        self.other.textChanged.connect(lambda _t: self._changed())
        self._load(lot_id)

    def _load(self, lot_id: int | None):
        dt = self.detail
        if dt:
            v = dt.view
            kind = "transfer" if v.kind.startswith("transfer") else v.kind
            self.lot.setCurrentIndex(max(0, self.lot.findData(v.lot_id)))
            self.day.setDate(_qdate(v.day))
            self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
            self.heads.setValue(abs(v.heads))
            self.weight.setText(stock.fmt_qty(v.weight).replace(".", "") if v.weight is not None else "")
            self.value.setText(_fmt(v.value))
            self.contact.setCurrentText(v.contact)
            if kind == "move":
                with Session() as s:
                    from finora.models import HerdEvent
                    self.area.setCurrentIndex(max(0, self.area.findData(s.get(HerdEvent, v.id).area_id)))
            if kind == "transfer":
                with Session() as s:
                    from finora.models import HerdEvent
                    self.to_lot.setCurrentIndex(max(0, self.to_lot.findData(s.get(HerdEvent, v.id).other_lot_id)))
            self.other.setText(_fmt(v.other_cost))
            self.desc.setText(v.description)
            self.inputs.lines = [livestock_line(i, q) for i, q in dt.inputs]
            self.fin.setChecked(dt.finance is not None)
            if dt.finance:
                self.fin_acc.setCurrentIndex(max(0, self.fin_acc.findData(dt.finance["account_id"])))
                self.fin_due.setDate(_qdate(dt.finance["due_date"]))
                self.fin_paid.setChecked(dt.finance["paid"])
        elif lot_id:
            self.lot.setCurrentIndex(max(0, self.lot.findData(lot_id)))
        self.delete_btn.setVisible(bool(dt))
        self._kind_changed(keep_cat=dt.finance["category_id"] if dt and dt.finance else None)

    def _kind_changed(self, keep_cat: int | None = None):
        k = self.kind.currentData()
        show = {"heads": k in WITH_HEADS, "weight": k in WITH_WEIGHT, "value": k in WITH_MONEY,
                "contact": k in WITH_MONEY, "area": k == "move", "to_lot": k == "transfer"}
        for key, ws in self.fields.items():
            for w in ws:
                w.setVisible(show[key])
        self.fields["heads"][0].label.setText("Cabeças pesadas" if k == "weighing" else "Cabeças")
        self.fin_box.setVisible(k in WITH_MONEY)
        if k in WITH_MONEY:
            sale = k == "sale"
            self.fin.setText("Lançar em Contas a receber" if sale else "Lançar em Contas a pagar")
            self.fin_paid.setText("Já foi recebido" if sale else "Já foi pago")
            kind = "income" if sale else "expense"
            if self.fin_cat.property("cat_kind") != kind:
                from finora.ui import category_pick
                category_pick.fill(self.fin_cat, self.entity_id, kind, keep_cat, t=self.t)
            for w in (self.fin_acc, self.fin_due, self.fin_cat, self.fin_paid):
                w.setEnabled(self.fin.isChecked())
            self.fin_due.setEnabled(self.fin.isChecked() and not self.fin_paid.isChecked())
        self.inputs.setVisible(k in WITH_INPUTS or bool(self.inputs.lines))
        self.filler.setVisible(self.inputs.isHidden())
        self._changed()

    def _money(self, w: QLineEdit) -> Decimal:
        try:
            return money.parse(w.text() or "0")
        except ValueError:
            return Decimal(0)

    def _data(self) -> EventData:
        k = self.kind.currentData()
        weight = None
        if k in WITH_WEIGHT and self.weight.text().strip():
            try:
                from finora.ui.stock_dialogs import parse_qty
                weight = parse_qty(self.weight.text())
            except ValueError:
                raise ValueError("Peso inválido.")
        fin = None
        if k in WITH_MONEY and self.fin.isChecked():
            paid = self.fin_paid.isChecked()
            fin = {"account_id": self.fin_acc.currentData(), "category_id": self.fin_cat.currentData(),
                   "due_date": self.day.date().toPython() if paid else self.fin_due.date().toPython(), "paid": paid}
        return EventData(lot_id=self.lot.currentData(), day=self.day.date().toPython(), kind=k,
                         heads=self.heads.value() if k in WITH_HEADS else 0, weight=weight,
                         value=self._money(self.value) if k in WITH_MONEY else Decimal(0),
                         other_cost=self._money(self.other),
                         inputs=[Use(ln.item_id, ln.quantity) for ln in self.inputs.lines],
                         area_id=self.area.currentData() if k == "move" else None,
                         to_lot_id=self.to_lot.currentData() if k == "transfer" else None,
                         contact=self.contact.currentText() if k in WITH_MONEY else "", finance=fin,
                         description=self.desc.text(),
                         location_id=self.locs[0][0] if len(self.locs) == 1 else None)

    def _changed(self, error: str | None = None):
        if error:
            self._err(error)
            return
        self.error.hide()
        day = self.day.date().toPython()
        with Session() as s:
            costs = [stock.average_cost(s, self.entity_id, ln.item_id, until=day) for ln in self.inputs.lines]
        self.inputs.fill(costs, self.currency)
        used = sum((Decimal(ln.quantity) * c for ln, c in zip(self.inputs.lines, costs)), Decimal(0))
        total = used.quantize(Decimal("0.01")) + self._money(self.other)
        self.cost_lbl.setText(f"<b>Custo: {money.fmt(total, self.currency)}</b>" if total else "")

    def _err(self, text: str):
        self.error.setText(text)
        self.error.show()

    def save(self):
        if self.lot.currentData() is None:
            self._err("Cadastre o lote antes (Novo lote).")
            return
        try:
            d = self._data()
            with Session() as s:
                self.event_id = livestock.save_event(s, self.entity_id, d, self.event_id)
        except ValueError as e:
            self._err(str(e))
            return
        self.done_text = f"{self.kind.currentText()} registrada no lote {self.lot.currentText().split(' (')[0]}."
        self.accept()

    def do_delete(self):
        if QMessageBox.question(self, "Excluir registro",
                                "Excluir este registro?\n\nOs insumos voltam ao estoque e a conta a pagar/receber "
                                "ligada vai para a lixeira.", QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            with Session() as s:
                livestock.delete_event(s, self.detail.view.id)
        except ValueError as e:
            self._err(str(e))
            return
        self.done_text = "Registro excluído."
        self.accept()


def livestock_line(item_id: int, quantity: Decimal):
    from finora.services.production import Line
    return Line(item_id, quantity)
