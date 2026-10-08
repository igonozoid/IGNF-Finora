"""Relatórios: DRE pessoal e fluxo de caixa projetado (mockup "Relatórios" e "DRE")."""
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP

from PySide6.QtCharts import QAreaSeries, QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QAbstractTableModel, QMargins, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QScrollArea, QStackedWidget, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget,
)
import qtawesome as qta

from finora.core import money
from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.services import export, reports
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.dashboard_page import KpiCard
from finora.ui.entries_page import MONTHS
from finora.ui.widgets import button, help_icon, lock_icon, set_tone, show_upgrade, themed_icon

SHORT = [m[:3].capitalize() for m in MONTHS]
COMPACT_BELOW = 900  # abaixo dessa largura, a lista de relatórios mostra só ícones
NARROW_BAR = 640     # abaixo dessa largura do relatório, a barra de ferramentas fica compacta

# (chave, rótulo, ícone, recurso pago ou None)
REPORTS = [
    ("dre", "DRE pessoal", "fa6s.chart-column", None),
    ("flow", "Fluxo de caixa", "fa6s.water", None),
    ("statement", "Extrato por conta", "fa6s.list", None),
    ("category", "Por categoria", "fa6s.tags", None),
    ("cost_center", "Por centro de custo", "fa6s.diagram-project", "cost_centers"),
    ("contact", "Por contato", "fa6s.address-book", None),
    ("agenda", "A pagar e a receber", "fa6s.calendar-days", None),
    ("overdue", "Inadimplência", "fa6s.hourglass-half", None),
    ("category_months", "Comparativo por categoria", "fa6s.table-columns", None),
    ("balance_history", "Evolução do patrimônio", "fa6s.chart-line", None),
    ("cash_history", "Entradas e saídas por mês", "fa6s.arrow-right-arrow-left", None),
    ("analytical", "Analítico", "fa6s.table-list", None),
    ("irpf", "Imposto de Renda", "fa6s.landmark", None),
    ("budget", "Orçado x realizado", "fa6s.bullseye", "budget"),
]
LOCK_MSG = {"budget": "Orçado x realizado é um recurso da edição Plus.",
            "cost_centers": "Relatório por centro de custo é um recurso da edição Plus.",
            "export": "Exportar para Excel e PDF é um recurso da edição Plus."}


def _feature(name: str) -> bool:
    return bool(allowed(current_edition(), name))


def whole(v: Decimal) -> str:
    """Valor sem centavos, no padrão do mockup da DRE: '−1.700', '58.400', '–' para zero."""
    n = int(v.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if n == 0:
        return "–"
    s = f"{abs(n):,}".replace(",", ".")
    return f"{money.MINUS}{s}" if n < 0 else s


class BackgroundDelegate(QStyledItemDelegate):
    """Pinta o BackgroundRole do modelo: com QSS em ::item, o Qt ignora essa cor sozinho."""

    def paint(self, painter, option, index):
        bg = index.data(Qt.BackgroundRole)
        if bg is not None:
            painter.fillRect(option.rect, bg)
        super().paint(painter, option, index)


def export_buttons(parent: QWidget, t: dict) -> QHBoxLayout:
    """Imprimir (todas as edições), Excel e PDF (pagas). A tela precisa ter export_sheet() e o sinal message."""
    row = QHBoxLayout()
    row.setSpacing(theme.SP_S)
    pr = button("Imprimir", "secondary", t, "fa6s.print", "fg")
    pr.setProperty("fullText", "Imprimir")
    pr.clicked.connect(lambda: _print(parent))
    row.addWidget(pr)
    parent.print_btn = pr
    parent.export_btns = [pr]
    for label, icon, kind in (("Excel", "fa6s.file-excel", "xlsx"), ("PDF", "fa6s.file-pdf", "pdf")):
        b = button(label, "secondary", t, icon, "fg")
        b.setProperty("fullText", label)
        parent.export_btns.append(b)
        if _feature("export"):
            b.clicked.connect(lambda _=False, k=kind: _export(parent, k))
        else:
            b.setToolTip(LOCK_MSG["export"])
            b.clicked.connect(lambda: show_upgrade(parent, LOCK_MSG["export"]))
        row.addWidget(b)
    if not _feature("export"):
        row.addWidget(lock_icon(LOCK_MSG["export"], t))
    return row


def _export(view: QWidget, kind: str):
    from finora.ui import exporting
    path = exporting.run(view, view.export_sheet(), kind)
    if path:
        view.message.emit(f"Salvo em {path}")


def _print(view: QWidget):
    from finora.ui import printing
    path = printing.open_print(view, view.export_sheet(), view.t)
    if path:
        view.message.emit(f"Salvo em {path}")


def compact_exports(view: QWidget, narrow: bool):
    for b in view.export_btns:
        b.setText("" if narrow else b.property("fullText"))
        if b is getattr(view, "print_btn", None):
            b.setToolTip("Imprimir (com prévia, retrato ou paisagem)")
            continue
        b.setToolTip(f"Exportar para {b.property('fullText')}" + ("" if _feature("export") else
                                                                    f" — {LOCK_MSG['export']}"))


def _table() -> QTableView:
    tv = QTableView()
    tv.setSelectionMode(QAbstractItemView.NoSelection)
    tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tv.setFocusPolicy(Qt.NoFocus)
    tv.setShowGrid(False)
    tv.setWordWrap(False)
    tv.verticalHeader().hide()
    tv.verticalHeader().setDefaultSectionSize(theme.ROW_H)
    tv.horizontalHeader().setHighlightSections(False)
    tv.setIconSize(QSize(11, 11))
    return tv


# ---------- DRE ----------
class DreModel(QAbstractTableModel):
    def __init__(self, t: dict, currency: str):
        super().__init__()
        self.t, self.currency = t, currency
        self.rep: reports.DreReport | None = None
        self.headers: list[str] = []

    def set_report(self, rep: reports.DreReport, t: dict):
        self.beginResetModel()
        self.rep, self.t = rep, t
        many_years = len({y for y, _m in rep.months}) > 1
        self.headers = (["DEMONSTRAÇÃO DO RESULTADO"]
                        + [f"{SHORT[m - 1]}/{str(y)[2:]}" if many_years else SHORT[m - 1] for y, m in rep.months]
                        + ["TOTAL", "AV %"])
        self.help_icon = qta.icon("fa6.circle-question", color=t["mut"])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or not self.rep else len(self.rep.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.headers[section]
            if role == Qt.TextAlignmentRole and section > 0:
                return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def _value(self, row: reports.DreRow, col: int) -> Decimal | None:
        n = len(self.rep.months)
        if 1 <= col <= n:
            return row.values[col - 1]
        if col == n + 1:
            return row.total
        return None

    def data(self, index, role=Qt.DisplayRole):
        row = self.rep.rows[index.row()]
        col = index.column()
        last = len(self.headers) - 1
        value = self._value(row, col)
        if role == Qt.DisplayRole:
            if col == 0:
                return ("      " if row.style == "detail" else "") + row.label
            if col == last:
                share = self.rep.share(row)
                return "—" if share is None else f"{share}%".replace(".", ",")
            return whole(value)
        if role == Qt.ToolTipRole:
            if col == 0:
                return row.help
            if value is not None:
                return money.fmt(value, self.currency)
        if role == Qt.DecorationRole and col == 0 and row.help:
            return self.help_icon
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignLeft if col == 0 else Qt.AlignRight) | Qt.AlignVCenter)
        if role == Qt.FontRole:
            f = theme.mono_font() if col > 0 else QFont()
            f.setBold(row.style in ("total", "result"))
            return f
        if role == Qt.BackgroundRole:
            if row.style == "total":
                return QBrush(QColor(self.t["panel"]))
            if row.style == "result":
                return QBrush(QColor(self.t["acc"]))
        if role == Qt.ForegroundRole:
            if row.style == "result":
                return QColor(self.t["on_acc"])
            if row.style == "detail" or col == last or (value is not None and value == 0):
                return QColor(self.t["mut"])
        return None


class DreView(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict):
        super().__init__()
        self.profile, self.t = profile, t
        self.regime = QComboBox()
        for k, label in reports.REGIMES.items():
            self.regime.addItem(label, k)
        self.period = QComboBox()
        for k, label in reports.PERIODS.items():
            self.period.addItem(label, k)
        self.details = QCheckBox("Mostrar subcategorias")
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        self.reg_lbl = reg_lbl = QLabel("Regime:")
        reg_lbl.setProperty("role", "muted")
        bar.addWidget(reg_lbl)
        bar.addWidget(self.regime)
        bar.addWidget(help_icon("Competência: conta tudo o que vence no mês, pago ou não.\n"
                                "Caixa: conta só o que foi pago, no mês em que foi pago.", t))
        bar.addSpacing(theme.SP_S)
        bar.addWidget(self.period)
        bar.addSpacing(theme.SP_S)
        bar.addWidget(self.details)
        bar.addStretch(1)
        bar.addLayout(export_buttons(self, t))

        self.model = DreModel(t, profile.currency)
        self.table = _table()
        self.table.setModel(self.model)
        self.table.setItemDelegate(BackgroundDelegate(self.table))
        self.note = QLabel(wordWrap=True)
        self.note.setProperty("role", "field")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.note)

        for w in (self.regime, self.period):
            w.currentIndexChanged.connect(self.refresh)
        self.details.toggled.connect(self.refresh)

    def refresh(self):
        months = reports.period_months(self.period.currentData())
        regime = self.regime.currentData()
        with Session() as s:
            rep = reports.dre(s, self.profile.id, months, regime, self.details.isChecked())
        self.model.set_report(rep, self.t)
        self.note.setText("Competência: considera tudo o que vence em cada mês, pago ou não. "
                          if regime == "accrual" else
                          "Caixa: considera só o que já foi pago, no mês do pagamento. ")
        self.note.setText(self.note.text() + "AV % = quanto cada linha representa das receitas do período. "
                          "Passe o mouse sobre um valor para ver os centavos.")
        self._resize_columns()

    def export_sheet(self) -> export.Sheet | None:
        rep = self.model.rep
        if rep is None:
            return None
        sheet = export.Sheet("DRE pessoal",
                             f"{self.period.currentText()} · regime de {self.regime.currentText().lower()}",
                             ["Demonstração do resultado"] + self.model.headers[1:-2] + ["Total", "AV %"],
                             currency=self.profile.currency)
        for row in rep.rows:
            share = rep.share(row)
            style = {"total": "bold", "result": "result", "detail": "detail"}.get(row.style, "")
            sheet.add([row.label, *row.values, row.total, "" if share is None else f"{share}%".replace(".", ",")],
                      style)
        sheet.footer = "AV % = quanto cada linha representa das receitas do período."
        return sheet

    def _resize_columns(self):
        hdr = self.table.horizontalHeader()
        n = self.model.columnCount()
        if not n:
            return
        hdr.setSectionResizeMode(QHeaderView.Fixed)
        widths = [84] * (n - 3) + [96, 60]
        for i, w in enumerate(widths, start=1):
            hdr.resizeSection(i, w)
        hdr.resizeSection(0, max(210, self.table.viewport().width() - sum(widths)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        narrow = self.width() < NARROW_BAR
        self.reg_lbl.setVisible(not narrow)
        self.details.setText("Subcategorias" if narrow else "Mostrar subcategorias")
        compact_exports(self, narrow)
        self._resize_columns()

    def apply_theme(self, t: dict):
        self.t = t
        self.model.t = t


# ---------- fluxo de caixa ----------
class FlowModel(QAbstractTableModel):
    HEAD = ["DATA", "O QUE ENTRA E SAI", "ENTRADAS", "SAÍDAS", "SALDO"]

    def __init__(self, t: dict, currency: str):
        super().__init__()
        self.t, self.currency = t, currency
        self.rows: list[tuple] = []

    def set_flow(self, flow: reports.CashFlow, t: dict):
        self.beginResetModel()
        self.t = t
        today = flow.days[0].day if flow.days else None
        self.rows = [("Hoje", "Saldo atual nas contas", None, None, flow.start_balance, "")]
        for d in flow.days:
            if not d.items:
                continue
            label = "Hoje" if d.day == today else d.day.strftime("%d/%m")
            text = ", ".join(d.items[:3]) + (f" e mais {len(d.items) - 3}" if len(d.items) > 3 else "")
            tip = "\n".join(d.items)
            if d.day == today and flow.overdue:
                text = f"Atrasados e de hoje: {text}"
            self.rows.append((label, text, d.inflow, d.outflow, d.balance, tip))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEAD)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.HEAD[section]
            if role == Qt.TextAlignmentRole and section >= 2:
                return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        day, text, inc, out, bal, tip = self.rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return day
            if col == 1:
                return text
            v = (inc, out, bal)[col - 2]
            if v is None or (col < 4 and v == 0):
                return ""
            return money.fmt(v, self.currency)
        if role == Qt.ToolTipRole and col == 1:
            return tip or None
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if col >= 2 else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == Qt.FontRole and col != 1:
            f = theme.mono_font()
            f.setBold(col == 4)
            return f
        if role == Qt.ForegroundRole:
            if col == 2:
                return QColor(self.t["pos"])
            if col == 4 and bal < 0:
                return QColor(self.t["neg"])
            if col == 0:
                return QColor(self.t["mut"])
        return None


class FlowChart(QChartView):
    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.Antialiasing)
        self.setFixedHeight(170)

    def set_flow(self, flow: reports.CashFlow, t: dict):
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setPlotAreaBackgroundVisible(False)
        chart.setMargins(QMargins(0, 0, 0, 0))
        chart.layout().setContentsMargins(0, 0, 0, 0)
        chart.legend().hide()
        # O QAreaSeries não fica dono das linhas: com o gráfico como pai, o Python não as destrói antes da hora.
        upper, lower, zero = QLineSeries(chart), QLineSeries(chart), QLineSeries(chart)
        values = [flow.start_balance] + [d.balance for d in flow.days]
        stamps = [flow.days[0].day] + [d.day for d in flow.days] if flow.days else []
        for i, (d, v) in enumerate(zip(stamps, values)):
            # o 1º ponto é o saldo de hoje antes dos lançamentos; o 2º, depois deles
            ms = datetime.combine(d, time(0 if i == 0 else 12)).timestamp() * 1000
            upper.append(ms, float(v))   # float só para desenhar
            lower.append(ms, 0.0)
            zero.append(ms, 0.0)
        area = QAreaSeries(upper, lower)
        fill = QColor(t["acc"])
        fill.setAlpha(60)
        area.setBrush(fill)
        area.setPen(QPen(QColor(t["acc"]), 2))
        chart.addSeries(area)
        ax = QDateTimeAxis()
        ax.setFormat("dd/MM")
        ax.setTickCount(6)
        ay = QValueAxis()
        lo, hi = min(values + [Decimal(0)]), max(values + [Decimal(0)])
        ay.setRange(float(lo), float(hi) if hi > lo else float(lo) + 1)
        ay.applyNiceNumbers()
        ay.setTickCount(5)
        ay.setLabelFormat("%.0f")
        small = QFont(self.font())
        small.setPointSizeF(theme.FONT_PT - 1)
        for axis in (ax, ay):
            axis.setLabelsColor(QColor(t["mut"]))
            axis.setLabelsFont(small)
            axis.setLinePen(QPen(QColor(t["line"])))
            axis.setGridLinePen(QPen(QColor(t["line"])))
        ax.setGridLineVisible(False)
        chart.addAxis(ax, Qt.AlignBottom)
        chart.addAxis(ay, Qt.AlignLeft)
        area.attachAxis(ax)
        area.attachAxis(ay)
        if lo < 0:
            zero.setPen(QPen(QColor(t["neg"]), 1, Qt.DashLine))
            chart.addSeries(zero)
            zero.attachAxis(ax)
            zero.attachAxis(ay)
        self.setChart(chart)


class FlowView(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict):
        super().__init__()
        self.profile, self.t = profile, t
        self.days = QComboBox()
        for n in (30, 60, 90):
            self.days.addItem(f"Próximos {n} dias", n)
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        bar.addWidget(self.days)
        bar.addWidget(help_icon("Parte do saldo de hoje nas contas e soma o que ainda vai entrar e sair,\n"
                                "dia a dia. Contas atrasadas entram como se fossem pagas hoje.", t))
        bar.addStretch(1)
        bar.addLayout(export_buttons(self, t))

        self.k_start = KpiCard("fa6s.wallet", "Saldo hoje", "Soma das contas ativas agora.", t)
        self.k_in = KpiCard("fa6s.arrow-down", "Vai entrar", "Receitas em aberto no período.", t)
        self.k_out = KpiCard("fa6s.arrow-up", "Vai sair", "Despesas em aberto no período, incluindo atrasadas.", t)
        self.k_end = KpiCard("fa6s.flag-checkered", "Saldo no fim", "Como o saldo deve ficar no último dia.", t)
        self.cards = [self.k_start, self.k_in, self.k_out, self.k_end]
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        self._cols = 0

        self.alert = QLabel(wordWrap=True)
        self.chart = FlowChart()
        self.model = FlowModel(t, profile.currency)
        self.table = _table()
        self.table.setModel(self.model)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        for col, w in ((0, 70), (2, 120), (3, 120), (4, 130)):
            hdr.resizeSection(col, w)

        self.table.setMinimumHeight(8 * theme.ROW_H)
        body = QWidget(objectName="pageBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(10)
        bl.addLayout(self.grid)
        bl.addWidget(self.alert)
        bl.addWidget(self.chart)
        bl.addWidget(self.table, 1)
        scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addLayout(bar)
        lay.addWidget(scroll, 1)
        self.days.currentIndexChanged.connect(self.refresh)
        self._arrange()

    def _arrange(self):
        cols = 2 if self.width() < 700 else 4
        if cols != self._cols:
            self._cols = cols
            for c in self.cards:
                self.grid.removeWidget(c)
            for i, c in enumerate(self.cards):
                self.grid.addWidget(c, i // cols, i % cols)
        self.table.setColumnHidden(3, self.width() < 560)
        compact_exports(self, self.width() < NARROW_BAR)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._arrange()

    def refresh(self):
        cur = self.profile.currency
        with Session() as s:
            flow = reports.cash_flow(s, self.profile.id, self.days.currentData())
        n = lambda k: f"{k} {'lançamento' if k == 1 else 'lançamentos'}"
        self.k_start.set(money.fmt(flow.start_balance, cur), "nas contas ativas",
                         "neg" if flow.start_balance < 0 else None)
        self.k_in.set(money.fmt(flow.inflow, cur), "receitas em aberto")
        self.k_out.set(money.fmt(flow.outflow, cur),
                       f"{n(flow.overdue)} atrasado{'s' if flow.overdue != 1 else ''}" if flow.overdue
                       else "despesas em aberto", note_tone="neg" if flow.overdue else None)
        end_day = flow.days[-1].day.strftime("%d/%m") if flow.days else ""
        self.k_end.set(money.fmt(flow.end_balance, cur), f"em {end_day}",
                       "neg" if flow.end_balance < 0 else "pos" if flow.end_balance > 0 else None)
        low = flow.lowest
        if low is not None and low.balance < 0:
            self.alert.setText(f"Atenção: o saldo fica negativo em {low.day.strftime('%d/%m')} "
                               f"(chega a {money.fmt(low.balance, cur)}). Veja o que dá para adiar ou antecipar.")
            set_tone(self.alert, "neg")
            self.alert.show()
        elif low is not None and flow.days:
            self.alert.setText(f"Menor saldo no período: {money.fmt(low.balance, cur)} em "
                               f"{low.day.strftime('%d/%m')}. É o ponto mais apertado do caixa.")
            set_tone(self.alert, "mut")
            self.alert.show()
        else:
            self.alert.hide()
        self.chart.set_flow(flow, self.t)
        self.model.set_flow(flow, self.t)

    def export_sheet(self) -> export.Sheet:
        sheet = export.Sheet("Fluxo de caixa", self.days.currentText(),
                             ["Data", "O que entra e sai", "Entradas", "Saídas", "Saldo"], currency=self.profile.currency)
        for day, text, inc, out, bal, tip in self.model.rows:
            sheet.add([day, "; ".join(tip.splitlines()) if tip else text, inc or None, -out if out else None, bal])
        return sheet

    def apply_theme(self, t: dict):
        self.t = t


# ---------- página ----------
class ReportsPage(QWidget):
    message = Signal(str)
    open_entry = Signal(int)
    open_statement = Signal(int, object)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.t = t
        from finora.ui import report_lists as rl
        self.views = {"dre": DreView(profile, t), "flow": FlowView(profile, t),
                      "statement": rl.AccountStatementView(profile, t), "category": rl.ByCategoryView(profile, t),
                      "cost_center": rl.ByCostCenterView(profile, t), "budget": rl.BudgetView(profile, t),
                      "contact": rl.ByContactView(profile, t), "overdue": rl.OverdueView(profile, t),
                      "analytical": rl.AnalyticalView(profile, t), "agenda": rl.AgendaView(profile, t),
                      "category_months": rl.CategoryMonthsView(profile, t),
                      "balance_history": rl.BalanceHistoryView(profile, t),
                      "cash_history": rl.CashHistoryView(profile, t), "irpf": rl.IrpfView(profile, t)}
        self.stack = QStackedWidget()
        for v in self.views.values():
            self.stack.addWidget(v)
            v.message.connect(self.message.emit)
            if hasattr(v, "open_entry"):
                v.open_entry.connect(self.open_entry.emit)
                v.open_statement.connect(self.open_statement.emit)

        self.nav = QWidget()
        nl = QVBoxLayout(self.nav)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(2)
        self.group = QButtonGroup(self, exclusive=True)
        self.buttons: list[tuple[QPushButton, str, str]] = []
        for i, (key, label, icon, feature) in enumerate(REPORTS):
            locked = feature is not None and not _feature(feature)
            b = QPushButton(label, objectName="navItem", checkable=not locked)
            b.setCursor(Qt.PointingHandCursor)
            themed_icon(b, "fa6s.lock" if locked else icon, t, "acc" if locked else "mut", 12)
            b.setToolTip(LOCK_MSG[feature] if locked else label)
            if locked:
                b.clicked.connect(lambda _=False, f=feature: show_upgrade(self, LOCK_MSG[f]))
            else:
                self.group.addButton(b, i)
            self.buttons.append((b, label, key))
            nl.addWidget(b)
        nl.addStretch(1)
        self.group.idClicked.connect(self._select)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addWidget(self.nav)
        root.addWidget(self.stack, 1)
        self.group.button(0).setChecked(True)
        self._current = "dre"

    def _select(self, i: int):
        self._current = REPORTS[i][0]
        self.stack.setCurrentWidget(self.views[self._current])
        self.views[self._current].refresh()

    def refresh(self):
        self.views[self._current].refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        compact = self.width() < COMPACT_BELOW
        self.nav.setFixedWidth(40 if compact else 180)
        for b, label, _key in self.buttons:
            b.setText("" if compact else label)

    def apply_theme(self, t: dict):
        self.t = t
        for v in self.views.values():
            v.apply_theme(t)
        if self.isVisible():
            self.refresh()
