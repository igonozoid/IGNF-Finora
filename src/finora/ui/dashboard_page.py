"""Dashboard: 4 indicadores, entradas x saídas (6 meses), saldos, vencimentos e maiores despesas."""
import math
from datetime import date

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
from PySide6.QtCore import QMargins, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QSizePolicy,
    QToolTip, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, dashboard
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.accounts_page import KIND_ICONS
from finora.ui.entries_page import MONTHS
from finora.ui.widgets import help_icon, icon_label, set_tone

SHORT = [m[:3].capitalize() for m in MONTHS]
NARROW = 760  # abaixo dessa largura, os painéis ficam um embaixo do outro


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if w := item.widget():
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            _clear(item.layout())


def _mono(pt: float = theme.FONT_PT) -> QFont:
    f = theme.mono_font()
    f.setPointSizeF(pt)
    return f


def _panel(title: str, t: dict, icon: str | None = None, icon_key: str = "acc") -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
    box = QFrame(objectName="card")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
    lay.setSpacing(theme.SP_S)
    head = QHBoxLayout()
    head.setSpacing(6)
    if icon:
        head.addWidget(icon_label(icon, t, icon_key, 12))
    head.addWidget(QLabel(title, objectName="sectionTitle"))
    head.addStretch(1)
    lay.addLayout(head)
    lay.addSpacing(theme.SP_S)
    return box, lay, head


def _nice_top(value: float, ticks: int = 4) -> float:
    """Topo "redondo" do eixo, para as marcas ficarem 0, 2.500, 5.000… em vez de 0, 2.221, 4.441…"""
    raw = value / ticks
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return step * ticks


class KpiCard(QFrame):
    def __init__(self, icon: str, label: str, help_text: str, t: dict):
        super().__init__(objectName="card")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_L, 10, theme.SP_L, 10)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(icon_label(icon, t, "mut", 11))
        lbl = QLabel(label)
        lbl.setProperty("role", "muted")
        top.addWidget(lbl)
        top.addStretch(1)
        top.addWidget(help_icon(help_text, t))
        lay.addLayout(top)
        self.value = QLabel()
        self.value.setFont(_mono(14))
        lay.addWidget(self.value)
        self.note = QLabel()
        self.note.setProperty("role", "field")
        lay.addWidget(self.note)

    def set(self, value: str, note: str, tone: str | None = None, note_tone: str | None = None):
        self.value.setText(value)
        set_tone(self.value, tone)
        self.note.setText(note)
        set_tone(self.note, note_tone)


class ClickRow(QFrame):
    clicked = Signal()

    def __init__(self):
        super().__init__(objectName="row")
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class FlowChart(QChartView):
    """Barras de entradas (âmbar) e saídas (cinza) por mês."""

    def __init__(self, t: dict, currency: str):
        super().__init__()
        self.currency = currency
        self.setRenderHint(QPainter.Antialiasing)
        self.setFixedHeight(210)
        self._flow = []
        self.t = t

    def set_data(self, flow: list[dashboard.MonthFlow], t: dict):
        self._flow, self.t = flow, t
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setPlotAreaBackgroundVisible(False)
        chart.setMargins(QMargins(0, 0, 0, 0))
        chart.layout().setContentsMargins(0, 0, 0, 0)
        chart.legend().hide()
        inc, out = QBarSet("Entradas"), QBarSet("Saídas")
        inc.setColor(QColor(t["acc"]))
        out_color = QColor(t["mut"])
        out_color.setAlpha(140)
        out.setColor(out_color)
        for b in (inc, out):
            b.setBorderColor(Qt.transparent)
        for f in flow:
            inc.append(float(f.income))   # float só para desenhar; os valores vêm de Decimal
            out.append(float(f.expense))
        series = QBarSeries()
        series.append(inc)
        series.append(out)
        series.setBarWidth(0.6)
        series.hovered.connect(self._hover)
        chart.addSeries(series)

        labels_font = QFont(self.font())
        labels_font.setPointSizeF(theme.FONT_PT - 1)
        ax = QBarCategoryAxis()
        ax.append([SHORT[f.month - 1] for f in flow])
        ay = QValueAxis()
        top = max([float(f.income) for f in flow] + [float(f.expense) for f in flow] + [1.0])
        ay.setRange(0, _nice_top(top))
        ay.setTickCount(5)
        ay.setLabelFormat("%.0f")
        for axis in (ax, ay):
            axis.setLabelsColor(QColor(t["mut"]))
            axis.setLabelsFont(labels_font)
            axis.setLinePen(QPen(QColor(t["line"])))
            axis.setGridLinePen(QPen(QColor(t["line"])))
        ax.setGridLineVisible(False)
        chart.addAxis(ax, Qt.AlignBottom)
        chart.addAxis(ay, Qt.AlignLeft)
        series.attachAxis(ax)
        series.attachAxis(ay)
        self.setChart(chart)

    def _hover(self, status: bool, index: int, barset: QBarSet):
        if not status:
            QToolTip.hideText()
            return
        f = self._flow[index]
        value = f.income if barset.label() == "Entradas" else f.expense
        QToolTip.showText(QCursor.pos(), f"{barset.label()} em {MONTHS[f.month - 1]}/{f.year}: "
                                         f"{money.fmt(value, self.currency)}")


class DashboardPage(QWidget):
    message = Signal(str)
    open_entry = Signal(int)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile = profile
        self.t = t

        cur = profile.currency
        self.k_balance = KpiCard("fa6s.wallet", "Saldo em contas", "Soma do saldo de todas as contas ativas.\n"
                                 "Cartões entram negativos (o que você deve).", t)
        self.k_rec = KpiCard("fa6s.arrow-down", "A receber (30 dias)",
                             "Dinheiro que deve entrar até daqui a 30 dias, incluindo o que já atrasou.", t)
        self.k_pay = KpiCard("fa6s.arrow-up", "A pagar (30 dias)",
                             "Contas a pagar até daqui a 30 dias, incluindo as atrasadas.", t)
        self.k_result = KpiCard("fa6s.chart-line", "Sobra do mês",
                                "Receitas menos despesas deste mês, pagas ou não.\n"
                                "Não conta o que foi para Investimentos/Reserva.\n"
                                "É a linha \"Sobra do mês\" da DRE pessoal.", t)
        self.kpi_grid = QGridLayout()
        self.kpi_grid.setSpacing(10)
        self.kpis = [self.k_balance, self.k_rec, self.k_pay, self.k_result]

        # Gráfico
        chart_box, cl, head = _panel("Entradas x Saídas · 6 meses", t)
        for label, key in (("Entradas", "acc"), ("Saídas", "mut")):
            head.addWidget(icon_label("fa6s.square", t, key, 9))
            lg = QLabel(label)
            lg.setProperty("role", "field")
            head.addWidget(lg)
            head.addSpacing(6)
        self.chart = FlowChart(t, cur)
        cl.addWidget(self.chart, 1)

        # Saldos por conta
        acc_box, self.acc_lay, _ = _panel("Saldos por conta", t)
        self.acc_rows = QVBoxLayout()
        self.acc_rows.setSpacing(0)
        self.acc_lay.addLayout(self.acc_rows)
        self.acc_lay.addStretch(1)

        # Vencimentos
        due_box, self.due_lay, _ = _panel("Vencendo nos próximos 7 dias", t, "fa6s.triangle-exclamation")
        self.due_rows = QVBoxLayout()
        self.due_rows.setSpacing(0)
        self.due_lay.addLayout(self.due_rows)
        self.due_lay.addStretch(1)

        # Maiores despesas
        cat_box, self.cat_lay, _ = _panel("Maiores despesas do mês", t)
        self.cat_rows = QVBoxLayout()
        self.cat_rows.setSpacing(theme.SP_M)
        self.cat_lay.addLayout(self.cat_rows)
        self.cat_lay.addStretch(1)

        self.row2 = QBoxLayout(QBoxLayout.LeftToRight)
        self.row2.setSpacing(10)
        self.row2.addWidget(chart_box, 2)
        self.row2.addWidget(acc_box, 1)
        self.row3 = QBoxLayout(QBoxLayout.LeftToRight)
        self.row3.setSpacing(10)
        self.row3.addWidget(due_box, 1)
        self.row3.addWidget(cat_box, 1)

        body = QWidget(objectName="pageBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(10)
        bl.addLayout(self.kpi_grid)
        bl.addLayout(self.row2)
        bl.addLayout(self.row3)
        bl.addStretch(1)
        scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.addWidget(scroll)
        self._cols = 0
        self._arrange()

    # ----- layout responsivo -----
    def _arrange(self):
        narrow = self.width() < NARROW + 28
        cols = 2 if narrow else 4
        if cols != self._cols:
            self._cols = cols
            for k in self.kpis:
                self.kpi_grid.removeWidget(k)
            for i, k in enumerate(self.kpis):
                self.kpi_grid.addWidget(k, i // cols, i % cols)
        direction = QBoxLayout.TopToBottom if narrow else QBoxLayout.LeftToRight
        self.row2.setDirection(direction)
        self.row3.setDirection(direction)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._arrange()

    # ----- dados -----
    def refresh(self):
        today = date.today()
        cur = self.profile.currency
        with Session() as s:
            k = dashboard.kpis(s, self.profile.id, today)
            flow = dashboard.monthly_flow(s, self.profile.id, 6, today)
            accs = accounts.list_accounts(s, self.profile.id)
            due = dashboard.due_soon(s, self.profile.id, 7, today)
            top = dashboard.top_expenses(s, self.profile.id, today.year, today.month)
        t = self.t

        plural = lambda n, one, many: f"{n} {one if n == 1 else many}"
        self.k_balance.set(money.fmt(k.balance, cur), plural(k.accounts, "conta", "contas"),
                           "neg" if k.balance < 0 else None)
        self.k_rec.set(money.fmt(k.receivable, cur), plural(k.receivable_n, "lançamento", "lançamentos"))
        late = f" · {plural(k.late_n, 'atrasado', 'atrasados')}" if k.late_n else ""
        self.k_pay.set(money.fmt(k.payable, cur), plural(k.payable_n, "lançamento", "lançamentos") + late,
                       note_tone="neg" if k.late_n else None)
        prev_name = MONTHS[(today.month - 2) % 12]
        diff = k.result - k.prev_result
        if diff == 0:
            note = f"igual a {prev_name}"
        else:
            note = f"{money.fmt(abs(diff), cur)} {'a mais' if diff > 0 else 'a menos'} que em {prev_name}"
        self.k_result.set(money.fmt(k.result, cur), note,
                          "pos" if k.result > 0 else "neg" if k.result < 0 else None)

        self.chart.set_data(flow, t)

        _clear(self.acc_rows)
        for a in accs:
            row = QHBoxLayout()
            row.setContentsMargins(0, 6, 0, 6)
            row.setSpacing(theme.SP_M)
            row.addWidget(icon_label(KIND_ICONS.get(a.kind, "fa6s.wallet"), t, "mut", 12))
            name = QLabel(a.name)
            name.setMinimumWidth(1)
            row.addWidget(name, 1)
            v = QLabel(money.fmt(a.balance, a.currency))
            v.setFont(_mono())
            row.addWidget(v)
            w = QFrame(objectName="listRow")
            w.setLayout(row)
            self.acc_rows.addWidget(w)
        if not accs:
            self.acc_rows.addWidget(self._muted("Nenhuma conta ativa."))

        _clear(self.due_rows)
        for e in due:
            row = ClickRow()
            row.setToolTip("Clique para abrir o lançamento")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 5, 0, 5)
            rl.setSpacing(theme.SP_M)
            d = QLabel(e.due_date.strftime("%d/%m"))
            d.setFont(_mono())
            d.setFixedWidth(44)
            set_tone(d, "neg" if e.is_late(today) else "mut")
            if e.is_late(today):
                d.setToolTip("Atrasado")
            desc = QLabel(e.description + (f" — {e.contact}" if e.contact else ""))
            desc.setMinimumWidth(1)
            v = QLabel(money.fmt(e.amount if e.kind == "income" else -e.amount, cur))
            v.setFont(_mono())
            if e.kind == "income":
                set_tone(v, "pos")
            rl.addWidget(d)
            rl.addWidget(desc, 1)
            rl.addWidget(v)
            row.clicked.connect(lambda i=e.id: self.open_entry.emit(i))
            self.due_rows.addWidget(row)
        if not due:
            self.due_rows.addWidget(self._muted("Nada vencendo nos próximos 7 dias."))

        _clear(self.cat_rows)
        biggest = top[0][1] if top else 0
        for label, value in top:
            box = QVBoxLayout()
            box.setSpacing(3)
            line = QHBoxLayout()
            line.addWidget(QLabel(label), 1)
            v = QLabel(money.fmt(value, cur))
            v.setFont(_mono())
            line.addWidget(v)
            bar = QProgressBar(textVisible=False, maximum=100)
            bar.setFixedHeight(5)
            bar.setValue(int(value * 100 / biggest) if biggest else 0)
            box.addLayout(line)
            box.addWidget(bar)
            self.cat_rows.addLayout(box)
        if not top:
            self.cat_rows.addWidget(self._muted("Nenhuma despesa neste mês ainda."))

    def _muted(self, text: str) -> QLabel:
        lbl = QLabel(text, wordWrap=True)
        lbl.setProperty("role", "muted")
        return lbl

    def apply_theme(self, t: dict):
        self.t = t
        if self.isVisible():
            self.refresh()
