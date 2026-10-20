"""Painel do Dashboard "Caixa × competência" e análise linear (Fase 3.12, do MCC). Plus/Pro (D3)."""
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.services import dashboard
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import help_icon, icon_label, set_tone, upgrade_box

HELP = ("Caixa: o que de fato entrou e saiu no período (pela data do pagamento).\n"
        "Competência: o que vence no período, pago ou não. \"Considerar vencidos\" soma\n"
        "também o que venceu antes e continua em aberto.\n"
        "Análise linear: receitas, despesas e o acumulado por dia, semana ou mês.")


class CashAccrualPanel(QFrame):
    """O que entrou/saiu (caixa) × o que vence (competência) num período, e a análise linear."""

    def __init__(self, profile: Profile, t: dict):
        super().__init__(objectName="card")
        self.profile, self.t = profile, t
        self.locked = not allowed(current_edition(), "mcc_reports")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        lay.setSpacing(theme.SP_M)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(icon_label("fa6s.scale-unbalanced", t, "acc", 12))
        head.addWidget(QLabel("Caixa × competência", objectName="sectionTitle"))
        head.addWidget(help_icon(HELP, t))
        head.addStretch(1)
        lay.addLayout(head)
        if self.locked:
            lay.addWidget(upgrade_box("Caixa × competência e análise linear são recursos das edições Plus e Pro.",
                                      t, self, compact=True))
            return

        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        self.period = QComboBox()
        for k, label in dashboard.CA_PERIODS.items():
            self.period.addItem(label, k)
        self.period.setCurrentIndex(self.period.findData("month"))
        today = QDate.currentDate()
        self.first = QDateEdit(QDate(today.year(), today.month(), 1), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.last = QDateEdit(today, calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.overdue = QCheckBox("Considerar vencidos")
        self.overdue.setToolTip("Soma na competência o que venceu antes do período e continua em aberto")
        for w in (self.period, self.first, self.last, self.overdue):
            bar.addWidget(w)
        bar.addStretch(1)
        lay.addLayout(bar)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP_L)
        grid.setVerticalSpacing(4)
        for c, title in enumerate(("", "RECEITAS", "DESPESAS", "RESULTADO")):
            lbl = QLabel(title)
            lbl.setProperty("role", "field")
            grid.addWidget(lbl, 0, c, alignment=Qt.AlignRight if c else Qt.AlignLeft)
        self.cells: dict[str, list[QLabel]] = {}
        for r, (key, label) in enumerate((("cash", "Caixa (pago e recebido)"),
                                          ("accrual", "Competência (vence no período)")), start=1):
            grid.addWidget(QLabel(label), r, 0)
            self.cells[key] = []
            for c in range(1, 4):
                v = QLabel(alignment=Qt.AlignRight | Qt.AlignVCenter)
                v.setFont(theme.mono_font())
                grid.addWidget(v, r, c)
                self.cells[key].append(v)
        grid.setColumnStretch(0, 1)
        lay.addLayout(grid)
        self.note = QLabel(wordWrap=True)
        self.note.setProperty("role", "muted")
        lay.addWidget(self.note)

        lbar = QHBoxLayout()
        lbar.setSpacing(theme.SP_M)
        ltitle = QLabel("Análise linear")
        ltitle.setProperty("role", "field")
        self.step = QComboBox()
        for k, label in dashboard.LINEAR_STEPS.items():
            self.step.addItem(label, k)
        self.regime = QComboBox()
        for k, label in dashboard.REGIMES.items():
            self.regime.addItem(label, k)
        for w in (ltitle, self.step, self.regime):
            lbar.addWidget(w)
        lbar.addStretch(1)
        lay.addLayout(lbar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["PERÍODO", "RECEITAS", "DESPESAS", "RESULTADO", "ACUMULADO"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        self.table.setFixedHeight(theme.ROW_H * 9)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 5):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        lay.addWidget(self.table)

        self.period.currentIndexChanged.connect(self._period_changed)
        self.first.dateChanged.connect(self.refresh)
        self.last.dateChanged.connect(self.refresh)
        self.overdue.toggled.connect(self.refresh)
        self.step.currentIndexChanged.connect(self.refresh)
        self.regime.currentIndexChanged.connect(self.refresh)
        self._sync_custom()

    def _sync_custom(self):
        custom = self.period.currentData() == "custom"
        self.first.setVisible(custom)
        self.last.setVisible(custom)

    def _period_changed(self):
        self._sync_custom()
        self.refresh()

    def range(self) -> tuple[date, date]:
        if self.period.currentData() == "custom":
            a, b = self.first.date(), self.last.date()
            first, last = date(a.year(), a.month(), a.day()), date(b.year(), b.month(), b.day())
            return (first, last) if first <= last else (last, first)
        return dashboard.ca_range(self.period.currentData())

    def refresh(self):
        if self.locked:
            return
        first, last = self.range()
        with Session() as s:
            ca = dashboard.cash_vs_accrual(s, self.profile.id, first, last, self.overdue.isChecked())
            rows = dashboard.linear(s, self.profile.id, first, last, self.step.currentData(),
                                    self.regime.currentData())
        cur = self.profile.currency
        for key, tot in (("cash", ca.cash), ("accrual", ca.accrual)):
            tones = ("pos", "neg", "pos" if tot.result > 0 else "neg")
            for lbl, v, tone in zip(self.cells[key], (tot.income, -tot.expense, tot.result), tones):
                lbl.setText(money.fmt(v, cur))
                set_tone(lbl, tone if v else None)
        late = ca.overdue
        if late.count:
            self.note.setText(f"Vencidos antes de {first:%d/%m/%Y} e ainda em aberto: {late.count} lançamento(s) — "
                              f"a receber {money.fmt(late.income, cur)}, a pagar {money.fmt(late.expense, cur)}"
                              + (" (já somados na competência)." if self.overdue.isChecked() else "."))
        else:
            self.note.setText(f"{first:%d/%m/%Y} a {last:%d/%m/%Y} · nada vencido em aberto antes do período.")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for c, v in enumerate((r.label, r.income, -r.expense, r.result, r.cumulative)):
                text = v if c == 0 else ("" if not v and c < 4 else money.fmt(v, cur))
                item = QTableWidgetItem(text)
                if c:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setFont(theme.mono_font())
                    if c in (3, 4) and v:
                        item.setForeground(QColor(self.t["pos" if v > 0 else "neg"]))
                self.table.setItem(i, c, item)
