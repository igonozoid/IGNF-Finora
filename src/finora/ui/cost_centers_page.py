"""Tela Centros de custo (mockup "Centros de custo"): orçado x realizado do mês para cada centro, e cadastro
lateral. Recurso das edições pagas; na Free a tela mostra o convite para upgrade."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.services import cost_centers
from finora.services.cost_centers import CostCenterView
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.entries_page import MONTHS
from finora.ui.widgets import button, field_label, help_icon, shared_checkbox, upgrade_box

PANEL_W = 280
STACK_BELOW = 760
LOCK_MSG = ("Centros de custo e orçamento por centro são recursos das edições Plus e Pro. Com eles você "
            "separa os gastos por Casa, Carro, Viagem… e vê quando um deles estoura o orçamento do mês.")
R = Qt.AlignRight | Qt.AlignVCenter
L = Qt.AlignLeft | Qt.AlignVCenter
C_NAME, C_BUDGET, C_SPENT, C_BAR, C_STATUS = range(5)


class UsageBar(QWidget):
    """Barrinha de consumo do orçamento (amarela; vermelha quando estoura)."""

    def __init__(self, share: Decimal | None, t: dict):
        super().__init__()
        self.share, self.t = share, t
        self.setMinimumWidth(60)

    def paintEvent(self, _e):
        if self.share is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = 6
        r = QRectF(4, (self.height() - h) / 2, self.width() - 8, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.t["line"]))
        p.drawRoundedRect(r, 3, 3)
        part = min(float(self.share), 1.0)
        if part > 0:
            p.setBrush(QColor(self.t["neg" if self.share > 1 else "acc"]))
            p.drawRoundedRect(QRectF(r.x(), r.y(), r.width() * part, h), 3, 3)
        p.end()


class CostCentersPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        today = date.today()
        self.period = (today.year, today.month)
        self.items: list[CostCenterView] = []
        self.editing: CostCenterView | None = None
        self.locked = not allowed(current_edition(), "cost_centers")
        if self.locked:
            root = QVBoxLayout(self)
            root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
            root.addWidget(upgrade_box(LOCK_MSG, t, self))
            root.addStretch(1)
            return

        # esquerda: barra + tabela
        self.title = QLabel(objectName="sectionTitle")
        self.show_inactive = QCheckBox("Mostrar inativos")
        self.new_btn = button("Novo centro", "secondary", t, "fa6s.plus", "fg")
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        bar.addWidget(self.title)
        bar.addWidget(help_icon("Realizado = despesas do mês (pela data da compra ou do vencimento) que têm esse "
                                "centro de custo.\nOrçado = quanto você quer gastar nele por mês.", t))
        bar.addStretch(1)
        bar.addWidget(self.show_inactive)
        bar.addWidget(self.new_btn)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["CENTRO DE CUSTO", "ORÇADO (MÊS)", "REALIZADO", "CONSUMO", "STATUS"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        for col, w in ((C_BUDGET, 120), (C_SPENT, 120), (C_BAR, 120), (C_STATUS, 90)):
            hdr.setSectionResizeMode(col, QHeaderView.Fixed)
            hdr.resizeSection(col, w)
            if col != C_BAR:
                self.table.horizontalHeaderItem(col).setTextAlignment(R)
        hdr.setSectionResizeMode(C_NAME, QHeaderView.Stretch)
        self.table.horizontalHeaderItem(C_NAME).setTextAlignment(L)
        self.empty = QLabel("Nenhum centro de custo ainda.\nCrie um ao lado — por exemplo \"Casa\", \"Carro\" "
                            "ou \"Viagem\" — e escolha-o nos lançamentos.", alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.footer = QLabel()
        self.footer.setProperty("role", "field")
        self.footer.setTextFormat(Qt.RichText)

        self.left = QWidget()
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        ll.addLayout(bar)
        ll.addWidget(self.table, 1)
        ll.addWidget(self.empty, 1)
        ll.addWidget(self.footer)

        # direita: formulário
        self.form = QFrame(objectName="card")
        fl = QVBoxLayout(self.form)
        fl.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        fl.setSpacing(theme.SP_M)
        self.form_title = QLabel(objectName="sectionTitle")
        fl.addWidget(self.form_title)
        self.name_edit = QLineEdit(maxLength=80, placeholderText="Ex.: Casa, Carro, Viagem")
        self.budget_edit = QLineEdit(placeholderText="Opcional")
        self.budget_edit.setFont(theme.mono_font())
        self.budget_edit.setAlignment(Qt.AlignRight)
        self.active = QCheckBox("Ativo (aparece nos lançamentos)")
        fl.addWidget(field_label("Nome", t))
        fl.addWidget(self.name_edit)
        fl.addWidget(field_label("Orçamento por mês", t, "Quanto você pretende gastar nesse centro a cada mês.\n"
                                                          "Deixe vazio para só acompanhar, sem limite."))
        fl.addWidget(self.budget_edit)
        fl.addWidget(self.active)
        self.shared = shared_checkbox()
        fl.addWidget(self.shared)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        fl.addWidget(self.error)
        btns = QHBoxLayout()
        self.save_btn = button("Salvar", "primary")
        self.cancel_btn = button("Cancelar", "secondary")
        self.delete_btn = button("Excluir", "danger")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        btns.addStretch(1)
        btns.addWidget(self.delete_btn)
        fl.addLayout(btns)

        self.panel = QWidget(objectName="pageBody")
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.form)
        pl.addStretch(1)
        self.panel_scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        self.panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.panel_scroll.setWidget(self.panel)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addWidget(self.left, 1)
        root.addWidget(self.panel_scroll)

        self._open = False
        self.show_inactive.toggled.connect(self.refresh)
        self.new_btn.clicked.connect(lambda: self._new(open_panel=True))
        self.cancel_btn.clicked.connect(self._cancel)
        self.save_btn.clicked.connect(self._save)
        self.delete_btn.clicked.connect(self._delete)
        for e in (self.name_edit, self.budget_edit):
            e.returnPressed.connect(self._save)
        self.table.cellClicked.connect(lambda r, _c: self._edit(self.items[r].id) if r < len(self.items) else None)
        self._new()

    # ----- período (o mês do cabeçalho) -----
    def set_period(self, year: int, month: int):
        self.period = (year, month)
        if self.isVisible():
            self.refresh()

    # ----- lista -----
    def refresh(self, select_id: int | None = None):
        if self.locked:
            return
        y, m = self.period
        self.title.setText(f"{MONTHS[m - 1].capitalize()} de {y}")
        with Session() as s:
            self.items = cost_centers.list_centers(s, self.profile.id, y, m,
                                                   include_inactive=self.show_inactive.isChecked())
        cur, t = self.profile.currency, self.t
        self.table.setRowCount(len(self.items))
        for r, c in enumerate(self.items):
            def item(text, align=R, tone=None, mono=True, bold=False):
                it = QTableWidgetItem(text)
                it.setTextAlignment(align)
                f = theme.mono_font() if mono else self.table.font()
                f.setBold(bold)
                it.setFont(f)
                if tone:
                    it.setForeground(QColor(t[tone]))
                return it

            self.table.setItem(r, C_NAME, item(c.name + ("" if c.is_active else " (inativo)"), L,
                                               None if c.is_active else "mut", mono=False))
            self.table.setItem(r, C_BUDGET, item(money.fmt(c.budget, cur) if c.budget else "—",
                                                 tone=None if c.budget else "mut"))
            spent = item(money.fmt(-c.spent, cur) if c.spent else "—", tone=None if c.spent else "mut")
            spent.setToolTip(f"{c.count} {'lançamento' if c.count == 1 else 'lançamentos'} no mês"
                             + (f" · recebido {money.fmt(c.received, cur)}" if c.received else ""))
            self.table.setItem(r, C_SPENT, spent)
            self.table.setCellWidget(r, C_BAR, UsageBar(c.share, t))
            pct = f"{c.share:.0%}" if c.share is not None else "—"
            status = {"none": ("—", "mut"), "ok": (pct, "mut"), "warn": (pct, "acc"),
                      "over": ("Estourou", "neg")}[c.status]
            st = item(status[0], tone=status[1], mono=False, bold=c.status == "over")
            if c.status == "over":
                st.setToolTip(f"Passou {money.fmt(c.spent - c.budget, cur)} do orçamento.")
            self.table.setItem(r, C_STATUS, st)
            if c.id == (select_id or (self.editing.id if self.editing else None)):
                self.table.selectRow(r)
        self.table.setVisible(bool(self.items))
        self.empty.setVisible(not self.items)
        budget = sum((c.budget or Decimal(0) for c in self.items if c.is_active), Decimal(0))
        spent = sum((c.spent for c in self.items), Decimal(0))
        self.footer.setText(f"Orçado <b>{money.fmt(budget, cur)}</b> &nbsp;·&nbsp; Realizado "
                            f"<b>{money.fmt(-spent, cur)}</b>" if self.items else "")
        self._arrange()

    # ----- formulário -----
    def _narrow(self) -> bool:
        return self.width() < STACK_BELOW

    def _arrange(self):
        narrow = self._narrow()
        self.panel_scroll.setVisible(not narrow or self._open)
        self.left.setVisible(not (narrow and self._open))
        self.panel_scroll.setFixedWidth(max(PANEL_W, self.width() - 28) if narrow else PANEL_W)
        self.cancel_btn.setVisible(narrow or self.editing is not None)
        # pouco espaço para a tabela: a barra de consumo sai (o % do status continua)
        table_w = self.width() - (0 if narrow else PANEL_W + theme.SP_L) - 28
        self.table.setColumnHidden(C_BAR, table_w < 640)

    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def _new(self, open_panel: bool = False):
        self.editing = None
        self.form_title.setText("Novo centro de custo")
        self.name_edit.clear()
        self.budget_edit.clear()
        self.active.setChecked(True)
        self.shared.setChecked(False)
        self.active.hide()
        self.delete_btn.hide()
        self._error(None)
        self._open = open_panel
        self.table.clearSelection()
        self._arrange()
        if open_panel:
            self.name_edit.setFocus()

    def _edit(self, cc_id: int):
        c = next((x for x in self.items if x.id == cc_id), None)
        if c is None:
            return
        self.editing = c
        self.form_title.setText("Editar centro de custo")
        self.name_edit.setText(c.name)
        self.budget_edit.setText(money.fmt(c.budget, self.profile.currency).split(" ", 1)[1] if c.budget else "")
        self.active.setChecked(c.is_active)
        self.shared.setChecked(c.shared)
        self.active.show()
        self.delete_btn.show()
        self._error(None)
        self._open = True
        self._arrange()

    def _cancel(self):
        self._new()

    def _save(self):
        text = self.budget_edit.text().strip()
        try:
            budget = money.parse(text) if text else None
        except ValueError:
            self._error("Orçamento inválido. Use o formato 1.234,56.")
            return
        try:
            with Session() as s:
                if self.editing:
                    cost_centers.update(s, self.editing.id, self.name_edit.text(), budget, self.active.isChecked(),
                                        shared=self.shared.isChecked())
                    cc_id, msg = self.editing.id, "Centro de custo atualizado."
                else:
                    cc_id = cost_centers.create(s, self.profile.id, self.name_edit.text(), budget,
                                                shared=self.shared.isChecked())
                    msg = "Centro de custo criado. Escolha-o nos lançamentos."
        except ValueError as e:
            self._error(str(e))
            return
        self.message.emit(msg)
        self._new()
        self.refresh(select_id=cc_id)

    def _delete(self):
        c = self.editing
        if c is None:
            return
        if QMessageBox.question(self, "Excluir centro de custo", f"Excluir \"{c.name}\"?") != QMessageBox.Yes:
            return
        try:
            with Session() as s:
                cost_centers.delete(s, c.id)
        except ValueError as e:
            self._error(str(e))
            return
        self.message.emit("Centro de custo excluído.")
        self._new()
        self.refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.locked:
            self._arrange()

    def apply_theme(self, t: dict):
        self.t = t
        if not self.locked and self.isVisible():
            self.refresh()
