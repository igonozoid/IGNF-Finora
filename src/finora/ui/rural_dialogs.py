"""Janelas da Agricultura: propriedade, área e atividade (com insumos usados e, na colheita, o que foi colhido)."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QSpinBox, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import rural, stock
from finora.services.rural import ActivityData, Use
from finora.ui import theme
from finora.ui.production_dialog import LinesBox
from finora.ui.widgets import button, field_label, help_icon

CENT = Decimal("0.01")


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


class _Form(QDialog):
    """Base das janelinhas de cadastro: formulário, erro e Salvar/Cancelar."""

    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.saved_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(theme.SP_M)
        self.form = QFormLayout()
        lay.addLayout(self.form)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancelar", "secondary")
        ok = button("Salvar", "primary")
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._ok)

    def _ok(self):
        try:
            self.saved_id = self.save()
        except ValueError as e:
            self.error.setText(str(e))
            self.error.show()
            return
        self.accept()

    def save(self) -> int:
        raise NotImplementedError


class FarmDialog(_Form):
    def __init__(self, parent, entity_id: int, farm: rural.FarmView | None = None):
        super().__init__(parent, "Editar propriedade" if farm else "Nova propriedade")
        self.entity_id, self.farm = entity_id, farm
        self.name = QLineEdit(maxLength=80, placeholderText="Ex.: Fazenda Singolare")
        self.city = QLineEdit(maxLength=80, placeholderText="Cidade / UF (opcional)")
        self.notes = QLineEdit(maxLength=300, placeholderText="Opcional")
        self.active = QCheckBox("Ativa")
        self.active.setChecked(True)
        for label, w in (("Nome", self.name), ("Local", self.city), ("Observação", self.notes), ("", self.active)):
            self.form.addRow(label, w)
        if farm:
            self.name.setText(farm.name)
            self.city.setText(farm.city)
            self.notes.setText(farm.notes)
            self.active.setChecked(farm.is_active)

    def save(self) -> int:
        with Session() as s:
            return rural.save_farm(s, self.entity_id, name=self.name.text(), city=self.city.text(),
                                   notes=self.notes.text(), is_active=self.active.isChecked(),
                                   farm_id=self.farm.id if self.farm else None)


class AreaDialog(_Form):
    def __init__(self, parent, entity_id: int, t: dict, area: rural.AreaView | None = None,
                 farm_id: int | None = None):
        super().__init__(parent, "Editar área" if area else "Nova área")
        self.entity_id, self.area = entity_id, area
        with Session() as s:
            farms = rural.farms(s, entity_id, include_inactive=bool(area))
        self.farm = QComboBox()
        for f in farms:
            self.farm.addItem(f.name, f.id)
        self.name = QLineEdit(maxLength=80, placeholderText="Ex.: Pomar 1, Talhão norte, Piquete 3")
        self.kind = QComboBox()
        for k, label in rural.AREA_KINDS.items():
            self.kind.addItem(label, k)
        self.crop = QLineEdit(maxLength=80, placeholderText="Ex.: Oliveira arbequina, Tifton, Milho")
        self.hectares = QLineEdit(placeholderText="Opcional")
        self.hectares.setFont(theme.mono_font())
        self.units = QSpinBox(maximum=10_000_000)
        self.units.setSpecialValueText("—")
        self.notes = QLineEdit(maxLength=300, placeholderText="Opcional")
        self.active = QCheckBox("Ativa")
        self.active.setChecked(True)
        units_row = QHBoxLayout()
        units_row.addWidget(self.units, 1)
        units_row.addWidget(help_icon("Quantidade de plantas, colmeias ou outra contagem útil da área (opcional).", t))
        for label, w in (("Propriedade", self.farm), ("Nome", self.name), ("Tipo", self.kind), ("Cultura", self.crop),
                         ("Hectares", self.hectares)):
            self.form.addRow(label, w)
        self.form.addRow("Plantas / colmeias", units_row)
        self.form.addRow("Observação", self.notes)
        self.form.addRow("", self.active)
        if farm_id:
            self.farm.setCurrentIndex(max(0, self.farm.findData(farm_id)))
        if area:
            self.farm.setCurrentIndex(max(0, self.farm.findData(area.farm_id)))
            self.name.setText(area.name)
            self.kind.setCurrentIndex(max(0, self.kind.findData(area.kind)))
            self.crop.setText(area.crop)
            if area.hectares is not None:
                self.hectares.setText(stock.fmt_qty(area.hectares).replace(".", ""))
            self.units.setValue(area.units or 0)
            self.notes.setText(area.notes)
            self.active.setChecked(area.is_active)

    def save(self) -> int:
        if self.farm.currentData() is None:
            raise ValueError("Cadastre a propriedade antes (Nova propriedade).")
        with Session() as s:
            return rural.save_area(s, self.entity_id, farm_id=self.farm.currentData(), name=self.name.text(),
                                   kind=self.kind.currentData(), crop=self.crop.text(),
                                   hectares=self.hectares.text().strip() or None,
                                   units=self.units.value() or None, notes=self.notes.text(),
                                   is_active=self.active.isChecked(), area_id=self.area.id if self.area else None)


class ActivityDialog(QDialog):
    def __init__(self, parent, entity_id: int, currency: str, t: dict, activity_id: int | None = None,
                 area_id: int | None = None):
        super().__init__(parent)
        self.entity_id, self.currency, self.t = entity_id, currency, t
        self.activity_id = activity_id
        self.done_text = ""
        self.setObjectName("wizard")
        self.resize(900, 680)
        self.setMinimumSize(720, 520)
        with Session() as s:
            items = stock.list_items(s, entity_id)
            self.area_list = rural.areas(s, entity_id, include_inactive=bool(activity_id))
            self.locs = [(loc.id, loc.name) for loc in stock.locations(s, entity_id)]
            self.detail = rural.get_activity(s, activity_id) if activity_id else None
            known = {i.id for i in items}
            if self.detail:
                for u in self.detail.inputs + self.detail.harvest:
                    if u.item_id not in known:
                        items.append(stock.get_item(s, u.item_id))
                        known.add(u.item_id)
        order = {"input": 0, "material": 1, "product": 2, "produced": 3}
        ins = sorted(items, key=lambda i: (order.get(i.kind, 9), i.name.lower()))
        outs = sorted(items, key=lambda i: (-order.get(i.kind, 0), i.name.lower()))
        self.setWindowTitle("Atividade — " + self.detail.kind_label if self.detail else "Nova atividade")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        head = QGridLayout()
        head.setHorizontalSpacing(theme.SP_M)
        head.setVerticalSpacing(3)
        self.area = QComboBox()
        for a in self.area_list:
            self.area.addItem(a.label + (f" ({a.crop})" if a.crop else ""), a.id)
        self.day = QDateEdit(_qdate(date.today()), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.kind = QComboBox()
        for k, label in rural.ACTIVITIES.items():
            self.kind.addItem(label, k)
        self.desc = QLineEdit(maxLength=200, placeholderText="O que foi feito (opcional)")
        self.loc = QComboBox()
        for lid, name in self.locs:
            self.loc.addItem(name, lid)
        fields = [("Área", self.area), ("Data", self.day), ("Atividade", self.kind)]
        if len(self.locs) > 1:
            fields.append(("Local do estoque", self.loc))
        for col, (label, w) in enumerate(fields):
            head.addWidget(field_label(label, t), 0, col)
            head.addWidget(w, 1, col)
        head.addWidget(self.desc, 2, 0, 1, len(fields))
        head.setColumnStretch(0, 3)
        lay.addLayout(head)

        self.inputs = LinesBox("Insumos usados (saem do estoque)", ins, t, False, self._changed)
        self.harvest = LinesBox("O que foi colhido (entra no estoque)", outs, t, False, self._changed,
                                check_stock=False)
        lay.addWidget(self.inputs, 1)
        lay.addWidget(self.harvest, 1)

        bottom = QGridLayout()
        bottom.setHorizontalSpacing(theme.SP_L)
        bottom.setVerticalSpacing(3)
        self.other = QLineEdit(placeholderText="0,00")
        self.hcost = QLineEdit()
        for w in (self.other, self.hcost):
            w.setFont(theme.mono_font())
            w.setAlignment(Qt.AlignRight)
            w.setMaximumWidth(140)
        other_lbl = QHBoxLayout()
        other_lbl.addWidget(field_label("Outros custos", t))
        other_lbl.addWidget(help_icon("Mão de obra, diária, hora-máquina, combustível… o que não sai do estoque.\n"
                                      "Entra só no custo da área; os pagamentos continuam em Lançamentos.", t))
        other_lbl.addStretch(1)
        self.hcost_lbl = QHBoxLayout()
        self.hcost_title = field_label("Custo que vai para a colheita", t)
        self.hcost_lbl.addWidget(self.hcost_title)
        self.hcost_help = help_icon("Em branco: tudo o que a área gastou até hoje e ainda não foi para uma colheita\n"
                                    "(o valor aparece em cinza). Informe outro valor se vier outra colheita da\n"
                                    "mesma safra e quiser dividir o custo.", t)
        self.hcost_lbl.addWidget(self.hcost_help)
        self.hcost_lbl.addStretch(1)
        bottom.addLayout(other_lbl, 0, 0)
        bottom.addWidget(self.other, 1, 0)
        bottom.addLayout(self.hcost_lbl, 0, 1)
        bottom.addWidget(self.hcost, 1, 1)
        self.notes = QLineEdit(maxLength=300, placeholderText="Observação (opcional)")
        bottom.addWidget(self.notes, 2, 0, 1, 2)
        self.cost_lbl = QLabel()
        self.cost_lbl.setFont(theme.mono_font())
        self.cost_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.cost_lbl, 0, 2, 3, 1)
        bottom.setColumnStretch(2, 1)
        lay.addLayout(bottom)

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        self.delete_btn = button("Excluir atividade", "link", t, "fa6s.trash")
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
        self.kind.currentIndexChanged.connect(lambda _i: self._changed())
        self.area.currentIndexChanged.connect(lambda _i: self._changed())
        self.day.dateChanged.connect(lambda _d: self._changed())
        self.other.textChanged.connect(lambda _t: self._changed())
        self.hcost.textChanged.connect(lambda _t: self._changed())
        self._load(area_id)

    def _load(self, area_id: int | None):
        d = self.detail
        if d:
            self.area.setCurrentIndex(max(0, self.area.findData(d.area_id)))
            self.day.setDate(_qdate(d.day))
            self.kind.setCurrentIndex(max(0, self.kind.findData(d.kind)))
            self.desc.setText(d.description)
            if d.location_id:
                self.loc.setCurrentIndex(max(0, self.loc.findData(d.location_id)))
            self.inputs.lines = [rural_line(u) for u in d.inputs]
            self.harvest.lines = [rural_line(u) for u in d.harvest]
            self.other.setText(_fmt(d.other_cost))
            if d.kind == "harvest":
                self.hcost.setText(_fmt(d.harvest_cost) or "0,00")
            self.notes.setText(d.notes)
        elif area_id:
            self.area.setCurrentIndex(max(0, self.area.findData(area_id)))
        self.delete_btn.setVisible(bool(d))
        self._changed()

    def _money(self, w: QLineEdit) -> Decimal | None:
        if not w.text().strip():
            return None
        try:
            return money.parse(w.text())
        except ValueError:
            return None

    def _data(self) -> ActivityData:
        harvest = self.kind.currentData() == "harvest"
        return ActivityData(area_id=self.area.currentData(), day=self.day.date().toPython(),
                            kind=self.kind.currentData(), description=self.desc.text(),
                            inputs=[Use(ln.item_id, ln.quantity) for ln in self.inputs.lines],
                            harvest=[Use(ln.item_id, ln.quantity) for ln in self.harvest.lines] if harvest else [],
                            other_cost=self._money(self.other) or Decimal(0),
                            harvest_cost=self._money(self.hcost) if harvest else None,
                            location_id=self.loc.currentData() if len(self.locs) > 1 else None,
                            notes=self.notes.text())

    def _changed(self, error: str | None = None):
        if error:
            self._err(error)
            return
        self.error.hide()
        harvest = self.kind.currentData() == "harvest"
        self.harvest.setVisible(harvest)
        for w in (self.hcost_title, self.hcost_help, self.hcost):
            w.setVisible(harvest)
        if self.area.currentData() is None:
            self.cost_lbl.setText("")
            return
        d = self._data()
        with Session() as s:
            in_costs = [stock.average_cost(s, self.entity_id, u.item_id, until=d.day) for u in d.inputs]
            suggested = rural.suggested_harvest_cost(s, self.entity_id, d, self.activity_id) if harvest else None
        self.inputs.fill(in_costs, self.currency)
        used = sum((Decimal(u.quantity) * c for u, c in zip(d.inputs, in_costs)), Decimal(0)).quantize(CENT)
        lines = [f"Insumos: {money.fmt(used, self.currency)}",
                 f"<b>Custo da atividade: {money.fmt(used + d.other_cost, self.currency)}</b>"]
        if harvest:
            self.hcost.setPlaceholderText(_fmt(suggested) or "0,00")
            cost = d.harvest_cost if d.harvest_cost is not None else suggested
            from finora.services import production
            unit = production.split_costs(cost, [production.Line(u.item_id, u.quantity) for u in d.harvest])
            self.harvest.fill(unit, self.currency)
            lines.append(f"Vai para a colheita: {money.fmt(cost, self.currency)}")
        self.cost_lbl.setText("<br>".join(lines))

    def _err(self, text: str):
        self.error.setText(text)
        self.error.show()

    def save(self):
        if self.area.currentData() is None:
            self._err("Cadastre a propriedade e a área antes (Áreas › Nova área).")
            return
        try:
            with Session() as s:
                self.activity_id = rural.save_activity(s, self.entity_id, self._data(), self.activity_id)
        except ValueError as e:
            self._err(str(e))
            return
        self.done_text = f"{self.kind.currentText()} registrada em {self.area.currentText()}."
        self.accept()

    def do_delete(self):
        if QMessageBox.question(self, "Excluir atividade",
                                "Excluir esta atividade?\n\nOs insumos voltam ao estoque e, se for colheita, o que foi "
                                "colhido sai do estoque.", QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            with Session() as s:
                rural.delete_activity(s, self.detail.id)
        except ValueError as e:
            self._err(str(e))
            return
        self.done_text = "Atividade excluída."
        self.accept()


def rural_line(u: rural.UseView):
    from finora.services.production import Line
    return Line(u.item_id, u.quantity)


def _fmt(v: Decimal | None) -> str:
    return money.fmt(v).split(" ", 1)[-1] if v else ""
