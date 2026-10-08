"""Dashboard: 4 indicadores, entradas x saídas (6 meses), saldos, vencimentos e maiores despesas."""
import math
from datetime import date, timedelta

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
from PySide6.QtCore import QMargins, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QSizePolicy,
    QToolTip, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, cards, dashboard, entries
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.accounts_page import KIND_ICONS
from finora.ui.entries_page import MONTHS
from finora.ui.widgets import button, help_icon, icon_label, set_tone

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


def nice_top(value: float, ticks: int = 4) -> float:
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
        self.label = lbl
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
        ay.setRange(0, nice_top(top))
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
    open_statement = Signal(int, object)     # (cartão, vencimento da fatura)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile = profile
        self.t = t
        today = date.today()
        self.period = (today.year, today.month)

        cur = profile.currency
        self.k_balance = KpiCard("fa6s.wallet", "Saldo em contas", "Soma das contas ativas (banco, carteira,\n"
                                 "investimentos). Cartões de crédito não entram: o que você\n"
                                 "deve neles aparece em \"A pagar\", pela fatura.", t)
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
        # Metas
        goals_box, self.goals_lay, ghead = _panel("Metas e objetivos", t, "fa6s.bullseye")
        self.goals_btn = button("Gerenciar", "link", t, "fa6s.pen")
        self.goals_btn.clicked.connect(lambda: self.open_goals())
        ghead.addWidget(self.goals_btn)
        self.goals_rows = QVBoxLayout()
        self.goals_rows.setSpacing(theme.SP_M)
        self.goals_lay.addLayout(self.goals_rows)
        self.goals_box = goals_box

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
        bl.addWidget(goals_box)
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
    def set_period(self, year: int, month: int):
        """Mês de referência (cabeçalho): sobra do mês, gráfico e maiores despesas.
        Saldo, a receber/a pagar em 30 dias e vencimentos continuam contando a partir de hoje."""
        if (year, month) != self.period:
            self.period = (year, month)
            if self.isVisible():
                self.refresh()

    def refresh(self):
        today = date.today()
        year, month = self.period
        ref = date(year, month, 1)
        prev = entries.add_months(ref, -1)
        cur = self.profile.currency
        with Session() as s:
            k = dashboard.kpis(s, self.profile.id, today)
            result = dashboard.month_result(s, self.profile.id, year, month)
            prev_result = dashboard.month_result(s, self.profile.id, prev.year, prev.month)
            flow = dashboard.monthly_flow(s, self.profile.id, 6, ref)
            accs = accounts.list_accounts(s, self.profile.id)
            due = dashboard.due_soon(s, self.profile.id, 7, today)
            bills = cards.open_statements(s, self.profile.id, today + timedelta(days=7), today)
            top = dashboard.top_expenses(s, self.profile.id, year, month)
        t = self.t

        plural = lambda n, one, many: f"{n} {one if n == 1 else many}"
        self.k_balance.set(money.fmt(k.balance, cur), plural(k.accounts, "conta", "contas"),
                           "neg" if k.balance < 0 else None)
        self.k_rec.set(money.fmt(k.receivable, cur), plural(k.receivable_n, "lançamento", "lançamentos"))
        late = f" · {plural(k.late_n, 'atrasado', 'atrasados')}" if k.late_n else ""
        self.k_pay.set(money.fmt(k.payable, cur), plural(k.payable_n, "lançamento", "lançamentos") + late,
                       note_tone="neg" if k.late_n else None)
        prev_name = MONTHS[prev.month - 1]
        diff = result - prev_result
        if diff == 0:
            note = f"igual a {prev_name}"
        else:
            note = f"{money.fmt(abs(diff), cur)} {'a mais' if diff > 0 else 'a menos'} que em {prev_name}"
        self.k_result.label.setText("Sobra do mês" if (year, month) == (today.year, today.month)
                                    else f"Sobra de {MONTHS[month - 1]}")
        self.k_result.set(money.fmt(result, cur), note,
                          "pos" if result > 0 else "neg" if result < 0 else None)

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
        # lançamentos e faturas de cartão, na ordem do vencimento
        items = [(e.due_date, e.description + (f" — {e.contact}" if e.contact else ""),
                  e.amount if e.kind == "income" else -e.amount, e.is_late(today),
                  "Clique para abrir o lançamento", lambda i=e.id: self.open_entry.emit(i)) for e in due]
        items += [(st.due, f"Fatura {st.account} {st.label}", -st.remaining, st.due < today,
                   "Clique para ver a fatura e pagar",
                   lambda a=st.account_id, d=st.due: self.open_statement.emit(a, d)) for st in bills]
        items.sort(key=lambda x: x[0])
        for when, text, value, is_late, tip, on_click in items[:8]:
            row = ClickRow()
            row.setToolTip(tip)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 5, 0, 5)
            rl.setSpacing(theme.SP_M)
            d = QLabel(when.strftime("%d/%m"))
            d.setFont(_mono())
            d.setFixedWidth(44)
            set_tone(d, "neg" if is_late else "mut")
            if is_late:
                d.setToolTip("Atrasado")
            desc = QLabel(text)
            desc.setMinimumWidth(1)
            v = QLabel(money.fmt(value, cur))
            v.setFont(_mono())
            if value > 0:
                set_tone(v, "pos")
            rl.addWidget(d)
            rl.addWidget(desc, 1)
            rl.addWidget(v)
            row.clicked.connect(on_click)
            self.due_rows.addWidget(row)
        if not items:
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
        self._fill_goals()

    def _fill_goals(self):
        from finora.services import goals
        from finora.ui.goals_dialog import describe
        _clear(self.goals_rows)
        with Session() as s:
            items = goals.list_goals(s, self.profile.id)
        for g in items:
            row = ClickRow()
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip("Clique para editar a meta")
            row.clicked.connect(lambda gid=g.id: self.open_goals(gid))
            box = QVBoxLayout(row)
            box.setContentsMargins(0, 2, 0, 2)
            box.setSpacing(3)
            line = QHBoxLayout()
            name = QLabel(g.name)
            line.addWidget(name, 1)
            pct = QLabel(f"{g.pct}%")
            pct.setFont(_mono())
            line.addWidget(pct)
            bar = QProgressBar(textVisible=False, maximum=100)
            bar.setFixedHeight(6)
            bar.setValue(g.pct)
            info = QLabel(describe(g, self.profile.currency))
            info.setProperty("role", "field")
            box.addLayout(line)
            box.addWidget(bar)
            box.addWidget(info)
            self.goals_rows.addWidget(row)
        if not items:
            hint = self._muted("Junte dinheiro com um objetivo: reserva de emergência, viagem, carro… "
                               "Clique em Gerenciar para criar a primeira meta.")
            self.goals_rows.addWidget(hint)

    def open_goals(self, select_id: int | None = None):
        from finora.ui.goals_dialog import GoalsDialog
        dlg = GoalsDialog(self, self.profile.id, self.profile.currency, self.t, select_id)
        dlg.exec()
        if dlg.changed:
            self.message.emit("Metas atualizadas.")
        self._fill_goals()

    def _muted(self, text: str) -> QLabel:
        lbl = QLabel(text, wordWrap=True)
        lbl.setProperty("role", "muted")
        return lbl

    def apply_theme(self, t: dict):
        self.t = t
        if self.isVisible():
            self.refresh()
