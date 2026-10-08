"""Gráficos dos relatórios: o mesmo desenho na tela (cores do tema) e na impressão/PDF (imagem, cores de papel)."""
from dataclasses import dataclass, field
from decimal import Decimal

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QPieSeries, QValueAxis,
)
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMargins, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from finora.ui import theme

PIE_MAX = 6          # fatias; o resto vira "Outros"


@dataclass
class ChartData:
    kind: str                                   # pie | bars | line
    labels: list[str]
    series: list[tuple[str, list[Decimal]]] = field(default_factory=list)
    currency: str = "BRL"

    @property
    def empty(self) -> bool:
        return not self.labels or not any(any(v for v in vals) for _n, vals in self.series)


def _palette(t: dict) -> list[QColor]:
    base = [t["acc"], t["pos"], t["neg"], t["mut"], t["fg"], t["line"]]
    out = [QColor(c) for c in base]
    for c, alpha in ((t["acc"], 120), (t["pos"], 120), (t["neg"], 120)):
        q = QColor(c)
        q.setAlpha(alpha)
        out.append(q)
    return out


def build(data: ChartData, t: dict, pt: float = theme.FONT_PT - 1) -> QChart:
    chart = QChart()
    chart.setBackgroundVisible(False)
    chart.setPlotAreaBackgroundVisible(False)
    chart.setMargins(QMargins(0, 0, 0, 0))
    chart.layout().setContentsMargins(0, 0, 0, 0)
    font = QFont()
    font.setPointSizeF(pt)
    colors = _palette(t)
    legend = chart.legend()
    legend.setLabelColor(QColor(t["fg"]))
    legend.setFont(font)
    if data.kind == "pie":
        values = list(zip(data.labels, data.series[0][1]))
        values = sorted(((lbl, abs(v)) for lbl, v in values if v), key=lambda x: -x[1])
        if len(values) > PIE_MAX:
            values = values[:PIE_MAX - 1] + [("Outros", sum((v for _l, v in values[PIE_MAX - 1:]), Decimal(0)))]
        total = sum((v for _l, v in values), Decimal(0)) or Decimal(1)
        pie = QPieSeries()
        pie.setHoleSize(0.45)
        for i, (lbl, v) in enumerate(values):
            sl = pie.append(f"{lbl} · {v * 100 / total:.0f}%".replace(".", ","), float(v))
            sl.setColor(colors[i % len(colors)])
            sl.setBorderColor(QColor(t["panel"]))
        chart.addSeries(pie)
        legend.setAlignment(Qt.AlignRight)
        return chart
    ax = QBarCategoryAxis()
    ax.append(data.labels)
    ay = QValueAxis()
    vals = [float(v) for _n, vs in data.series for v in vs] or [0.0]
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    pad = (hi - lo) * 0.08 or 1.0
    ay.setRange(lo - (pad if lo < 0 else 0), hi + pad)
    ay.setTickCount(5)
    ay.applyNiceNumbers()
    ay.setLabelFormat("%.0f")
    small = QFont(font)
    if len(data.labels) > 6:                  # 12 meses: rótulos menores para não cortar
        small.setPointSizeF(font.pointSizeF() * 0.75)
    for axis in (ax, ay):
        axis.setLabelsColor(QColor(t["mut"]))
        axis.setLabelsFont(small if axis is ax else font)
        axis.setLinePen(QPen(QColor(t["line"])))
        axis.setGridLinePen(QPen(QColor(t["line"])))
    ax.setGridLineVisible(False)
    chart.addAxis(ax, Qt.AlignBottom)
    chart.addAxis(ay, Qt.AlignLeft)
    if data.kind == "bars":
        colors = [QColor(t["acc"]), QColor(t["mut"])] + colors[3:]    # entrou âmbar, saiu cinza (como no Dashboard)
        series = QBarSeries()
        for i, (name, vs) in enumerate(data.series):
            bs = QBarSet(name)
            bs.setColor(colors[i % len(colors)])
            bs.setBorderColor(Qt.transparent)
            for v in vs:
                bs.append(float(v))
            series.append(bs)
        series.setBarWidth(0.65)
        chart.addSeries(series)
        series.attachAxis(ax)
        series.attachAxis(ay)
    else:
        for i, (name, vs) in enumerate(data.series):
            line = QLineSeries(name=name)
            pen = QPen(colors[i % len(colors)])
            pen.setWidthF(2.2)
            line.setPen(pen)
            line.setPointsVisible(True)
            for x, v in enumerate(vs):
                line.append(QPointF(x, float(v)))
            chart.addSeries(line)
            ax_line = QValueAxis()            # posição x = índice do mês; os rótulos ficam no eixo de categorias
            ax_line.setRange(-0.5, len(vs) - 0.5)
            ax_line.setVisible(False)
            chart.addAxis(ax_line, Qt.AlignBottom)
            line.attachAxis(ax_line)
            line.attachAxis(ay)
    legend.setVisible(len(data.series) > 1)
    legend.setAlignment(Qt.AlignTop)
    return chart


def png(data: ChartData, width: int = 1000, height: int = 320) -> bytes:
    """Imagem do gráfico com as cores de papel (tema claro, fundo branco), para impressão e PDF."""
    paper = dict(theme.LIGHT)
    view = QChartView(build(data, paper, pt=17))     # a imagem sai reduzida à metade na folha
    view.setRenderHint(QPainter.Antialiasing)
    view.setStyleSheet("background: #ffffff; border: 0;")
    view.resize(width, height)
    view.chart().resize(width, height)
    pix = view.grab()
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.WriteOnly)
    pix.save(dev, "PNG")
    view.deleteLater()
    return bytes(buf)

