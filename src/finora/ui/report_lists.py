"""Relatórios em lista: extrato por conta, por categoria, por contato e inadimplência."""
import re
from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, budgets, export, reports
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import help_icon, set_tone

R = Qt.AlignRight | Qt.AlignVCenter
L = Qt.AlignLeft | Qt.AlignVCenter


class TableReport(QWidget):
    """Base: barra (filtros + exportar), tabela e rodapé. Duplo clique numa linha com lançamento abre-o."""
    message = Signal(str)
    open_entry = Signal(int)
    open_statement = Signal(int, object)
    COLUMNS: list[tuple[str, int | None, bool]] = []      # (título, largura ou None = estica, é valor?)
    TITLE = ""
    COMPACT = False          # valores sem o símbolo da moeda (relatórios mês a mês, colunas estreitas)
    HAS_CHART = False        # o relatório desenha um gráfico (self.chart, montado no refresh)

    def __init__(self, profile: Profile, t: dict):
        super().__init__()
        self.profile, self.t = profile, t
        self.bar = QHBoxLayout()
        self.bar.setSpacing(theme.SP_M)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.set_columns(self.COLUMNS)
        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.footer = QLabel(wordWrap=True)
        self.footer.setTextFormat(Qt.RichText)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(10)
        self.lay.addLayout(self.bar)
        self.chart = None
        self.chart_view = None
        if self.HAS_CHART:
            from PySide6.QtCharts import QChartView
            from PySide6.QtGui import QPainter
            self.chart_view = QChartView()
            self.chart_view.setRenderHint(QPainter.Antialiasing)
            self.chart_view.setFixedHeight(200)
            self.chart_view.hide()
            self.lay.addWidget(self.chart_view)
        self.lay.addWidget(self.table, 1)
        self.lay.addWidget(self.empty, 1)
        self.lay.addWidget(self.footer)
        self._targets: list = []
        self._rows: list[dict] = []
        self.table.cellDoubleClicked.connect(self._double)

    def set_columns(self, columns: list[tuple[str, int | None, bool]]):
        """Colunas (título, largura ou None = estica, é valor?). Relatórios mês a mês mudam com o período."""
        self.COLUMNS = list(columns)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([c[0] for c in columns])
        hdr = self.table.horizontalHeader()
        for i, (_title, width, is_value) in enumerate(columns):
            if width is None:
                hdr.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.Fixed)
                hdr.resizeSection(i, width)
            self.table.horizontalHeaderItem(i).setTextAlignment(R if is_value else L)

    def months_box(self) -> QComboBox:
        box = QComboBox()
        for k, label in reports.PERIODS.items():
            box.addItem(label, k)
        box.setCurrentIndex(box.findData("6m"))
        box.currentIndexChanged.connect(self.refresh)
        return box

    @staticmethod
    def month_title(y: int, m: int, many_years: bool) -> str:
        from finora.ui.entries_page import MONTHS
        short = MONTHS[m - 1][:3].upper()
        return f"{short}/{str(y)[2:]}" if many_years else short

    # ----- ajuda para montar a barra -----
    def period_box(self) -> QComboBox:
        box = QComboBox()
        for k, label in reports.LIST_PERIODS.items():
            box.addItem(label, k)
        box.currentIndexChanged.connect(self.refresh)
        return box

    def finish_bar(self, help_text: str | None = None):
        from finora.ui.reports_page import export_buttons     # evita import circular
        if help_text:
            self.bar.addWidget(help_icon(help_text, self.t))
        if self.HAS_CHART:
            from finora.core import settings
            self.chart_check = QCheckBox("Gráfico")
            self.chart_check.setToolTip("Mostrar o gráfico (ele também sai na impressão e no PDF)")
            self.chart_check.setChecked(settings.get_report_charts())
            self.chart_check.toggled.connect(self._chart_toggled)
            self.bar.addWidget(self.chart_check)
        self.bar.addStretch(1)
        self.bar.addLayout(export_buttons(self, self.t))

    # ----- tabela -----
    def fill(self, rows: list[dict], empty_text: str):
        """rows: {"cells": [...], "tones": {col: tone}, "bold": bool, "muted": bool, "target": (tipo, ...)}
        Célula Decimal vira dinheiro; int vira texto. Os valores crus vão para a exportação."""
        self._rows = rows
        self.table.setRowCount(len(rows))
        self._targets = []
        bold = QFont()
        bold.setBold(True)
        for r, row in enumerate(rows):
            self._targets.append(row.get("target"))
            for c, value in enumerate(row["cells"]):
                item = QTableWidgetItem(self.cell_text(value))
                is_value = self.COLUMNS[c][2]
                if is_value:
                    f = theme.mono_font()
                    f.setBold(row.get("bold", False))
                    item.setFont(f)
                    item.setTextAlignment(R)
                else:
                    item.setTextAlignment(L)
                    if row.get("bold"):
                        item.setFont(bold)
                tone = row.get("tones", {}).get(c) or ("mut" if row.get("muted") else None)
                if tone:
                    item.setForeground(QBrush(QColor(self.t[tone])))
                if row.get("target"):
                    item.setToolTip("Duplo clique para abrir")
                self.table.setItem(r, c, item)
        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)
        self.empty.setText(empty_text)
        self._show_chart()

    # ----- gráfico -----
    def _chart_on(self) -> bool:
        return self.HAS_CHART and hasattr(self, "chart_check") and self.chart_check.isChecked() \
            and self.chart is not None and not self.chart.empty

    def _show_chart(self):
        if self.chart_view is None:
            return
        if self._chart_on():
            from finora.ui import report_charts
            self.chart_view.setChart(report_charts.build(self.chart, self.t))
        self.chart_view.setVisible(self._chart_on())

    def _chart_toggled(self, on: bool):
        from finora.core import settings
        settings.set_report_charts(on)
        self._show_chart()

    def _double(self, row: int, _col: int):
        target = self._targets[row] if row < len(self._targets) else None
        if not target:
            return
        if target[0] == "entry":
            self.open_entry.emit(target[1])
        elif target[0] == "statement":
            self.open_statement.emit(target[1], target[2])

    def fmt(self, v: Decimal) -> str:
        return money.fmt(v, self.profile.currency)

    def cell_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, Decimal):
            text = self.fmt(value)
            if self.COMPACT:                      # "− R$ 1.800,00" -> "−1.800,00"
                text = text.replace(f"{money.symbol(self.profile.currency)} ", "").replace(" ", "")
            return text
        return str(value)

    # ----- exportar -----
    def subtitle(self) -> str:
        return self.period.currentText() if hasattr(self, "period") else ""

    def export_sheet(self) -> export.Sheet:
        sheet = export.Sheet(self.TITLE, self.subtitle(), [export.header(c[0]) for c in self.COLUMNS],
                             currency=self.profile.currency)
        for row in self._rows:
            style = "bold" if row.get("bold") else "detail" if row.get("muted") else "indent" if row.get("indent") else ""
            cells = list(row["cells"])
            if row.get("indent") and isinstance(cells[0], str):      # o recuo da tela vira estilo na exportação
                cells[0] = cells[0].strip()
            sheet.add(cells, style)
        text = re.sub(r"<[^>]+>", "", self.footer.text()).replace("&nbsp;", " ")
        sheet.footer = " ".join(text.split())
        if self._chart_on():
            from finora.ui import report_charts
            sheet.chart = report_charts.png(self.chart)
        return sheet

    def apply_theme(self, t: dict):
        self.t = t
        self._show_chart()


# ---------- extrato por conta ----------
class AccountStatementView(TableReport):
    TITLE = "Extrato por conta"

    def subtitle(self) -> str:
        return f"{self.account.currentText()} · {self.period.currentText()}" + \
            (" · previsto" if self.forecast.isChecked() else "")
    COLUMNS = [("DATA", 70, False), ("DESCRIÇÃO", None, False), ("CATEGORIA", 170, False),
               ("ENTRADA", 120, True), ("SAÍDA", 120, True), ("SALDO", 130, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.account = QComboBox()
        self.account.setMinimumWidth(160)
        self.account.currentIndexChanged.connect(self.refresh)
        self.period = self.period_box()
        self.forecast = QCheckBox("Previsto")
        self.forecast.setToolTip("Inclui o que está em aberto, na data do vencimento (edições Plus e Pro)")
        self.forecast.toggled.connect(self._forecast_toggled)
        self.bar.addWidget(self.account)
        self.bar.addWidget(self.period)
        self.bar.addWidget(self.forecast)
        self.finish_bar("Tudo o que entrou e saiu da conta no período, na data em que aconteceu,\n"
                        "com o saldo depois de cada movimento. Só o que já foi pago/recebido.\n"
                        "No cartão, as compras aparecem na data da compra.\n"
                        "Previsto: inclui também o que está em aberto, na data do vencimento (em cinza);\n"
                        "o saldo anterior passa a contar o que venceu antes e continua em aberto.")

    def _forecast_toggled(self, on: bool):
        from finora.core.licensing import allowed, current_edition
        if on and not allowed(current_edition(), "mcc_reports"):
            from finora.ui.widgets import show_upgrade
            self.forecast.setChecked(False)
            show_upgrade(self, "O extrato no modo previsto é um recurso das edições Plus e Pro.")
            return
        self.refresh()

    def _fill_accounts(self):
        keep = self.account.currentData()
        with Session() as s:
            accs = accounts.list_accounts(s, self.profile.id, include_inactive=True)
        self.account.blockSignals(True)
        self.account.clear()
        for a in accs:
            self.account.addItem(a.name + ("" if a.is_active else " (inativa)"), a.id)
        idx = self.account.findData(keep)
        self.account.setCurrentIndex(idx if idx >= 0 else 0)
        self.account.blockSignals(False)

    def refresh(self):
        self._fill_accounts()
        acc_id = self.account.currentData()
        if acc_id is None:
            self.fill([], "Cadastre uma conta para ver o extrato.")
            self.footer.clear()
            return
        first, last = reports.period_range(self.period.currentData())
        with Session() as s:
            st = reports.account_statement(s, acc_id, first, last, forecast=self.forecast.isChecked())
        rows = [{"cells": [first.strftime("%d/%m"), "Saldo anterior", "", None, None, st.opening],
                 "bold": True, "tones": {5: "neg" if st.opening < 0 else None}}]
        for line in st.lines:
            rows.append({"cells": [line.day.strftime("%d/%m"), line.description + (" (em aberto)" if line.pending else ""),
                                   line.category, line.inflow or None, -line.outflow if line.outflow else None,
                                   line.balance],
                         "tones": {3: None if line.pending else "pos", 1: None,
                                   5: "neg" if line.balance < 0 else None},
                         "muted": line.pending, "target": ("entry", line.entry_id)})
        self.fill(rows, "")
        final = "Saldo final previsto" if self.forecast.isChecked() else "Saldo final"
        self.footer.setText(f"Entradas <b>{self.fmt(st.inflow)}</b> &nbsp;·&nbsp; Saídas <b>{self.fmt(-st.outflow)}</b>"
                            f" &nbsp;·&nbsp; {final} <b>{self.fmt(st.closing)}</b>")


# ---------- por categoria ----------
class ByCategoryView(TableReport):
    TITLE = "Por categoria"
    HAS_CHART = True
    COLUMNS = [("CATEGORIA", None, False), ("TIPO", 90, False), ("QTD.", 60, True), ("TOTAL", 130, True),
               ("% DO TIPO", 90, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.period_box()
        self.bar.addWidget(self.period)
        self.finish_bar("Quanto entrou e saiu em cada categoria no período (pago ou não),\n"
                        "do maior para o menor. % = parte do total de receitas ou de despesas.")

    def refresh(self):
        first, last = reports.period_range(self.period.currentData())
        with Session() as s:
            data = reports.by_category(s, self.profile.id, first, last)
        totals = {k: sum((r.total for r in data if r.kind == k), Decimal(0)) for k in ("income", "expense")}
        groups: dict[str, Decimal] = {}
        for r in data:
            if r.kind == "expense":
                groups[r.group] = groups.get(r.group, Decimal(0)) + r.total
        from finora.ui.report_charts import ChartData
        self.chart = ChartData("pie", list(groups), [("Despesas", list(groups.values()))], self.profile.currency)
        rows = []
        for r in data:
            label = r.category if r.group == r.category else f"{r.group} › {r.category}"
            share = (r.total * 100 / totals[r.kind]) if totals[r.kind] else Decimal(0)
            rows.append({"cells": [label, "Receita" if r.kind == "income" else "Despesa", r.count,
                                   r.total if r.kind == "income" else -r.total,
                                   f"{share:.1f}%".replace(".", ",")],
                         "tones": {3: "pos" if r.kind == "income" else None}})
        self.fill(rows, "Nenhum lançamento com categoria neste período.")
        self.footer.setText(f"Receitas <b>{self.fmt(totals['income'])}</b> &nbsp;·&nbsp; "
                            f"Despesas <b>{self.fmt(-totals['expense'])}</b>")


# ---------- por contato ----------
class ByContactView(TableReport):
    TITLE = "Por contato"
    COLUMNS = [("CONTATO", None, False), ("QTD.", 60, True), ("ME PAGOU", 130, True), ("EU PAGUEI", 130, True),
               ("SALDO", 130, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.period_box()
        self.bar.addWidget(self.period)
        self.finish_bar("Quanto cada contato te pagou e quanto você pagou a ele no período (pago ou não).")

    def refresh(self):
        first, last = reports.period_range(self.period.currentData())
        with Session() as s:
            data = reports.by_contact(s, self.profile.id, first, last)
        rows = [{"cells": [r.contact, r.count, r.received or None, -r.paid if r.paid else None,
                           r.received - r.paid],
                 "tones": {2: "pos", 4: "neg" if r.received < r.paid else "pos" if r.received > r.paid else None}}
                for r in data]
        self.fill(rows, "Nenhum lançamento com contato neste período.")
        rec = sum((r.received for r in data), Decimal(0))
        paid = sum((r.paid for r in data), Decimal(0))
        self.footer.setText(f"Recebido <b>{self.fmt(rec)}</b> &nbsp;·&nbsp; Pago <b>{self.fmt(-paid)}</b>")


# ---------- por centro de custo ----------
class ByCostCenterView(TableReport):
    TITLE = "Por centro de custo"
    COLUMNS = [("CENTRO DE CUSTO", None, False), ("QTD.", 60, True), ("ORÇADO", 120, True),
               ("GASTO", 120, True), ("DIFERENÇA", 120, True), ("RECEBIDO", 120, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.period_box()
        self.bar.addWidget(self.period)
        self.finish_bar("Quanto foi gasto (e recebido) em cada centro de custo no período, pago ou não.\n"
                        "Orçado = orçamento mensal do centro x meses do período. Diferença negativa = estourou.")

    def refresh(self):
        first, last = reports.period_range(self.period.currentData())
        with Session() as s:
            data = reports.by_cost_center(s, self.profile.id, first, last)
        rows = []
        for r in data:
            diff = (r.budget - r.spent) if r.budget is not None else None
            rows.append({"cells": [r.name, r.count, r.budget, -r.spent if r.spent else None, diff,
                                   r.received or None],
                         "tones": {4: "neg" if diff is not None and diff < 0 else "pos" if diff else None, 5: "pos"},
                         "muted": r.name == "Sem centro de custo"})
        self.fill(rows, "Nenhum centro de custo com lançamentos neste período.\n"
                        "Cadastre em Centros de custo e escolha-o nos lançamentos.")
        spent = sum((r.spent for r in data if r.name != "Sem centro de custo"), Decimal(0))
        self.footer.setText(f"Gasto com centro de custo <b>{self.fmt(-spent)}</b>")


# ---------- orçado x realizado ----------
class BudgetView(TableReport):
    TITLE = "Orçado x realizado"
    COLUMNS = [("CATEGORIA", None, False), ("ORÇADO/MÊS", 120, True), ("ORÇADO NO PERÍODO", 130, True),
               ("REALIZADO", 120, True), ("SALDO", 120, True), ("CONSUMO", 110, False), ("STATUS", 80, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.period_box()
        self.bar.addWidget(self.period)
        self.only_used = QCheckBox("Só com orçamento ou gasto")
        self.only_used.toggled.connect(self.refresh)
        self.bar.addWidget(self.only_used)
        self.finish_bar("Dê dois cliques no ORÇADO/MÊS de uma categoria para definir quanto pretende gastar\n"
                        "nela por mês (vazio apaga). Grupo sem orçamento próprio usa a soma das subcategorias.\n"
                        "Realizado = despesas do período pela data da compra/vencimento, pagas ou não.")
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.itemChanged.connect(self._edited)
        self._data: list[budgets.BudgetRow] = []

    def refresh(self):
        first, last = reports.period_range(self.period.currentData())
        with Session() as s:
            self._data = budgets.report(s, self.profile.id, first, last, self.only_used.isChecked())
        many = first.month != last.month or first.year != last.year
        self.table.setColumnHidden(2, not many)
        rows = []
        for r in self._data:
            status = {"none": "", "ok": f"{r.share:.0%}" if r.share is not None else "",
                      "warn": f"{r.share:.0%}" if r.share is not None else "", "over": "Estourou"}[r.status]
            rows.append({"cells": [("      " if r.level else "") + r.name, r.monthly, r.planned,
                                   -r.actual if r.actual else None, r.left, "", status],
                         "bold": r.level == 0,
                         "tones": {1: "mut" if r.own is None else None, 4: "neg" if r.left and r.left < 0 else None,
                                   6: {"over": "neg", "warn": "acc"}.get(r.status, "mut")}})
        self.table.blockSignals(True)
        self.fill(rows, "Nenhuma categoria de despesa para orçar.")
        from finora.ui.cost_centers_page import UsageBar
        for i, r in enumerate(self._data):
            item = self.table.item(i, 1)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setToolTip("Dois cliques para mudar" + ("" if r.own is not None or r.monthly is None
                                                       else " (hoje é a soma das subcategorias)"))
            for c in (0, 2, 3, 4, 5, 6):
                it = self.table.item(i, c)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setCellWidget(i, 5, UsageBar(r.share, self.t))
        self.table.blockSignals(False)
        planned = sum((r.planned or Decimal(0) for r in self._data if r.level == 0), Decimal(0))
        actual = sum((r.actual for r in self._data if r.level == 0), Decimal(0))
        self.footer.setText(f"Orçado <b>{self.fmt(planned)}</b> &nbsp;·&nbsp; Realizado <b>{self.fmt(-actual)}</b>"
                            f" &nbsp;·&nbsp; Saldo <b>{self.fmt(planned - actual)}</b>")

    def _edited(self, item):
        if item.column() != 1 or item.row() >= len(self._data):
            return
        row = self._data[item.row()]
        text = item.text().strip()
        try:
            value = money.parse(text) if text and text != "—" else None
        except ValueError:
            QMessageBox.warning(self, "Orçamento", "Valor inválido. Use o formato 1.234,56.")
            self.refresh()
            return
        try:
            with Session() as s:
                budgets.set_budget(s, self.profile.id, row.category_id, value)
        except ValueError as e:
            QMessageBox.warning(self, "Orçamento", str(e))
        else:
            self.message.emit(f"Orçamento de {row.name}: {self.fmt(value) if value else 'removido'}.")
        self.refresh()


# ---------- analítico ----------
class AnalyticalView(TableReport):
    TITLE = "Analítico"
    COLUMNS = [("DATA", 70, False), ("DESCRIÇÃO", None, False), ("CATEGORIA", 150, False),
               ("CENTRO DE CUSTO", 120, False), ("CONTATO", 130, False), ("CONTA", 110, False),
               ("OBSERVAÇÕES", 160, False), ("VALOR", 120, True)]
    KINDS = {"all": "Receitas e despesas", "income": "Só receitas", "expense": "Só despesas"}

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.period_box()
        self.bar.addWidget(self.period)
        self.kind = QComboBox()
        for k, label in self.KINDS.items():
            self.kind.addItem(label, k)
        self.kind.currentIndexChanged.connect(self.refresh)
        self.bar.addWidget(self.kind)
        self.finish_bar("Cada receita e despesa do período (pela data da compra/vencimento), pagas ou não,\n"
                        "com categoria, centro de custo, contato, conta e observações. Valores na moeda principal.\n"
                        "Dois cliques abrem o lançamento.")

    def subtitle(self) -> str:
        return f"{self.period.currentText()} · {self.kind.currentText()}"

    def refresh(self):
        first, last = reports.period_range(self.period.currentData())
        with Session() as s:
            data = reports.analytical(s, self.profile.id, first, last, self.kind.currentData())
        many_years = first.year != last.year
        rows = [{"cells": [e.competence_date.strftime("%d/%m/%y" if many_years else "%d/%m"),
                           e.description + (f" ({e.installment})" if e.installment else ""),
                           e.category or "Sem categoria", e.cost_center or "", e.contact or "", e.account,
                           " ".join((e.notes or "").split()),
                           e.base_amount if e.kind == "income" else -e.base_amount],
                 "tones": {7: "pos" if e.kind == "income" else None, 2: None if e.category else "mut", 6: "mut"},
                 "target": ("entry", e.id)} for e in data]
        self.fill(rows, "Nenhuma receita ou despesa neste período.")
        inc = sum((e.base_amount for e in data if e.kind == "income"), Decimal(0))
        exp = sum((e.base_amount for e in data if e.kind == "expense"), Decimal(0))
        self.footer.setText(f"{len(data)} lançamentos &nbsp;·&nbsp; Receitas <b>{self.fmt(inc)}</b> &nbsp;·&nbsp; "
                            f"Despesas <b>{self.fmt(-exp)}</b> &nbsp;·&nbsp; Resultado <b>{self.fmt(inc - exp)}</b>")


# ---------- a pagar e a receber ----------
class AgendaView(TableReport):
    TITLE = "A pagar e a receber"
    ALL_COLUMNS = [("VENC.", 80, False), ("DESCRIÇÃO", None, False), ("CONTATO", 150, False), ("CONTA", 110, False),
                   ("A RECEBER", 120, True), ("A PAGAR", 120, True)]
    COLUMNS = ALL_COLUMNS

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.kind = QComboBox()
        for k, label in reports.AGENDA_KINDS.items():
            self.kind.addItem(label, k)
        self.period = QComboBox()
        for k, label in reports.AGENDA_PERIODS.items():
            self.period.addItem(label, k)
        today = QDate.currentDate()
        self.first = QDateEdit(today, calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.last = QDateEdit(today.addDays(29), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.until = QLabel("até")
        self.overdue = QCheckBox("Com as vencidas")
        self.overdue.setToolTip("Inclui também as contas que já venceram antes do período e continuam em aberto")
        for w in (self.kind, self.period, self.first, self.until, self.last, self.overdue):
            self.bar.addWidget(w)
        self._show_dates()
        self.kind.currentIndexChanged.connect(self.refresh)
        self.period.currentIndexChanged.connect(self._period_changed)
        self.first.dateChanged.connect(self.refresh)
        self.last.dateChanged.connect(self.refresh)
        self.overdue.toggled.connect(self.refresh)
        self.finish_bar("Contas em aberto que vencem no período, semana a semana, com o total de cada semana.\n"
                        "Escolha só a pagar, só a receber ou as duas, e um período qualquer em Período personalizado.\n"
                        "Marque Com as vencidas para incluir o que já venceu e não foi pago. "
                        "Dois cliques abrem o lançamento.")

    def _show_dates(self):
        custom = self.period.currentData() == "custom"
        for w in (self.first, self.until, self.last):
            w.setVisible(custom)

    def _period_changed(self):
        if self.period.currentData() == "custom":       # começa no período que estava na tela
            prev = self._range or reports.agenda_range("30")
            for w, d in ((self.first, prev[0]), (self.last, prev[1])):
                w.blockSignals(True)
                w.setDate(QDate(d.year, d.month, d.day))
                w.blockSignals(False)
        self._show_dates()
        self.refresh()

    _range = None

    def date_range(self) -> tuple[date, date]:
        if self.period.currentData() == "custom":
            return self.first.date().toPython(), self.last.date().toPython()
        return reports.agenda_range(self.period.currentData())

    def subtitle(self) -> str:
        first, last = self.date_range()
        parts = [f"{first:%d/%m/%Y} a {last:%d/%m/%Y}"]
        if self.period.currentData() != "custom":
            parts.insert(0, self.period.currentText())
        if self.kind.currentData():
            parts.append(self.kind.currentText())
        if self.overdue.isChecked():
            parts.append("com as vencidas")
        return " · ".join(parts)

    def refresh(self):
        kind = self.kind.currentData()
        keep = [i for i in range(6) if not (i == 4 and kind == "expense") and not (i == 5 and kind == "income")]
        self.set_columns([self.ALL_COLUMNS[i] for i in keep])
        first, last = self._range = self.date_range()
        if first > last:
            self.fill([], "A data inicial é depois da final.")
            self.footer.clear()
            return
        with Session() as s:
            data = reports.agenda(s, self.profile.id, first, last, kind, self.overdue.isChecked())
        rows, week, rec_w, pay_w = [], None, Decimal(0), Decimal(0)

        def row(cells: list, **extra) -> dict:
            tones = {keep.index(c): tone for c, tone in extra.pop("tones", {}).items() if c in keep}
            return {"cells": [cells[i] for i in keep], "tones": tones, **extra}

        def close_week():
            if week is not None:
                title = (f"Total das vencidas antes de {first:%d/%m}" if week == "old"
                         else f"Total da semana de {week:%d/%m}")
                rows.append(row(["", title, "", "", rec_w or None, -pay_w if pay_w else None], bold=True))

        for e in data:
            start = "old" if e.due_date < first else e.due_date - timedelta(days=e.due_date.weekday())
            if start != week:
                close_week()
                week, rec_w, pay_w = start, Decimal(0), Decimal(0)
            inc = e.base_amount if e.kind == "income" else None
            out = -e.base_amount if e.kind == "expense" else None
            rec_w += inc or 0
            pay_w += -out if out else 0
            rows.append(row([e.due_date.strftime("%d/%m/%y"), e.description, e.contact or "", e.account, inc, out],
                            tones={4: "pos", **({0: "neg"} if e.due_date < date.today() else {})},
                            target=("entry", e.id)))
        close_week()
        self.fill(rows, "Nenhuma conta em aberto vencendo nesse período.")
        rec = sum((e.base_amount for e in data if e.kind == "income"), Decimal(0))
        pay = sum((e.base_amount for e in data if e.kind == "expense"), Decimal(0))
        parts = [] if kind == "expense" else [f"A receber <b>{self.fmt(rec)}</b>"]
        if kind != "income":
            parts.append(f"A pagar <b>{self.fmt(-pay)}</b>")
        if not kind:
            parts.append(f"Saldo <b>{self.fmt(rec - pay)}</b>")
        self.footer.setText(f"{len(data)} {'conta' if len(data) == 1 else 'contas'} &nbsp;·&nbsp; "
                            + " &nbsp;·&nbsp; ".join(parts))


# ---------- imposto de renda ----------
class IrpfView(TableReport):
    TITLE = "Imposto de Renda"
    COLUMNS = [("NOME", None, False), ("CPF/CNPJ", 150, False), ("ANO ANTERIOR", 130, True), ("ANO", 130, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.year = QSpinBox(minimum=2000, maximum=2100, value=date.today().year - 1)
        self.year.setPrefix("Ano-calendário ")
        self.year.valueChanged.connect(lambda _v: self.refresh())
        self.bar.addWidget(self.year)
        self.finish_bar("Resumo para a declaração do IRPF: o que você recebeu (por fonte pagadora), o que pagou de\n"
                        "saúde e educação (por quem recebeu) e o saldo das contas em 31/12. Tudo pela data do\n"
                        "pagamento. Saúde e Educação são os grupos da DRE das suas categorias.\n"
                        "O Finora não sabe as regras de cada gasto (remédio não deduz, educação tem limite):\n"
                        "confira antes de digitar no programa da Receita.")

    def subtitle(self) -> str:
        return f"Ano-calendário {self.year.value()} (declaração de {self.year.value() + 1})"

    def refresh(self):
        from finora.services import irpf
        y = self.year.value()
        self.set_columns([("NOME", None, False), ("CPF/CNPJ", 150, False), (str(y - 1), 130, True),
                          (str(y), 130, True)])
        with Session() as s:
            rep = irpf.report(s, self.profile.id, y)
        rows: list[dict] = []

        def section(title: str, items: list, total_label: str, show_doc: bool = True):
            if not items:
                return
            rows.append({"cells": [title, "", None, None], "bold": True})
            for r in items:
                doc = r.document if r.document else ("falta" if show_doc and r.missing_doc else "")
                rows.append({"cells": [f"    {r.name}", doc, r.previous or None, r.value], "indent": True,
                             "tones": {1: "neg"} if doc == "falta" else {}})
            prev, cur = rep.total(items)
            rows.append({"cells": [total_label, "", prev, cur], "bold": True})

        section("Rendimentos recebidos (por fonte pagadora)", rep.incomes, "Total recebido")
        for key, label in irpf.DEDUCTIBLE.items():
            section(f"Pagamentos de {label.lower()} (por quem recebeu)", rep.deductible[key], f"Total de {label.lower()}")
        section("Saldo das contas em 31/12 (Bens e Direitos)", rep.balances, "Total em 31/12", show_doc=False)
        self.fill(rows, f"Nada recebido, pago em saúde/educação ou guardado em {y}.")
        notes = []
        if rep.missing:
            notes.append(f"<b>{rep.missing}</b> {'linha está' if rep.missing == 1 else 'linhas estão'} sem CPF/CNPJ "
                         "ou sem contato: complete em Contatos (a Receita pede o documento de quem pagou/recebeu).")
        notes.append("Valores na moeda principal. Confira com os informes de rendimentos e recibos.")
        self.footer.setText(" ".join(notes))


# ---------- comparativo mensal por categoria ----------
class CategoryMonthsView(TableReport):
    TITLE = "Comparativo por categoria"
    COMPACT = True
    HAS_CHART = True
    COLUMNS = [("CATEGORIA", None, False)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.months_box()
        self.bar.addWidget(self.period)
        self.finish_bar("Cada categoria mês a mês (pela data da compra/vencimento, pago ou não), com a média\n"
                        "mensal e o total. Bom para ver o que subiu ou caiu de um mês para o outro.")

    # pontos de troca para o demonstrativo anual (AnnualView)
    def _months(self) -> list[tuple[int, int]]:
        return reports.period_months(self.period.currentData())

    def _by(self) -> str:
        return "category"

    def _label(self, r) -> str:
        return r.category if r.group == r.category else f"{r.group} › {r.category}"

    def refresh(self):
        months = self._months()
        many = len({y for y, _m in months}) > 1
        title = reports.GROUP_BY[self._by()][0].upper()
        self.set_columns([(title, None, False)] + [(self.month_title(y, m, many), 84, True) for y, m in months]
                         + [("MÉDIA", 90, True), ("TOTAL", 96, True)])
        with Session() as s:
            data = reports.by_month(s, self.profile.id, months, self._by())
        from finora.ui.report_charts import ChartData
        sums = {k: [sum((r.values[i] for r in data if r.kind == k), Decimal(0)) for i in range(len(months))]
                for k in ("income", "expense")}
        self.chart = ChartData("bars", [self.month_title(y, m, many) for y, m in months],
                               [("Receitas", sums["income"]), ("Despesas", sums["expense"])], self.profile.currency)
        rows, last_kind = [], None
        for r in data:
            if r.kind != last_kind:
                rows.append({"cells": ["Receitas" if r.kind == "income" else "Despesas"] + [None] * (len(months) + 2),
                             "bold": True})
                last_kind = r.kind
            sign = 1 if r.kind == "income" else -1
            rows.append({"cells": [self._label(r)] + [sign * v if v else None for v in r.values]
                         + [sign * r.average, sign * r.total],
                         "tones": {len(months) + 1: "mut"}})
        self.fill(rows, "Nenhum lançamento nesse período.")
        self.footer.setText("Valores na moeda principal. Média = total dividido pelo número de meses do período.")


# ---------- evolução do patrimônio ----------
class BalanceHistoryView(TableReport):
    TITLE = "Evolução do patrimônio"
    COMPACT = True
    HAS_CHART = True
    COLUMNS = [("CONTA", None, False)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.months_box()
        self.bar.addWidget(self.period)
        self.finish_bar("Saldo de cada conta no último dia de cada mês, e o total (sem os cartões, que são\n"
                        "dívida e aparecem à parte). Contas em outra moeda entram no total pela cotação do mês.")

    def refresh(self):
        months = reports.period_months(self.period.currentData())
        many = len({y for y, _m in months}) > 1
        self.set_columns([("CONTA", None, False)] + [(self.month_title(y, m, many), 92, True) for y, m in months])
        with Session() as s:
            data = reports.balance_history(s, self.profile.id, months)
        rows = []
        self.chart = None
        for r in data:
            label = r.account + ("" if r.currency == self.profile.currency else f" ({r.currency}, convertido)")
            rows.append({"cells": [label] + list(r.base_values), "muted": r.kind == "card",
                         "tones": {i + 1: "neg" for i, v in enumerate(r.base_values) if v < 0}})
        if data:
            total = [sum((r.base_values[i] for r in data if r.kind != "card"), Decimal(0)) for i in range(len(months))]
            cards_ = [sum((r.base_values[i] for r in data if r.kind == "card"), Decimal(0)) for i in range(len(months))]
            rows.append({"cells": ["Total (sem cartões)"] + total, "bold": True})
            from finora.ui.report_charts import ChartData
            series = [("Total (sem cartões)", total)]
            if any(cards_):
                series.append(("Patrimônio líquido", [a + b for a, b in zip(total, cards_)]))
            self.chart = ChartData("line", [self.month_title(y, m, many) for y, m in months], series,
                                   self.profile.currency)
            if any(cards_):
                rows.append({"cells": ["Cartões (dívida)"] + cards_, "muted": True})
                rows.append({"cells": ["Patrimônio líquido"] + [a + b for a, b in zip(total, cards_)], "bold": True})
        self.fill(rows, "Nenhuma conta cadastrada.")
        if data and len(months) > 1:
            first, last = total[0], total[-1]
            self.footer.setText(f"Variação no período: <b>{self.fmt(last - first)}</b> (de {self.fmt(first)} para "
                                f"{self.fmt(last)})")
        else:
            self.footer.clear()


# ---------- entradas e saídas por mês ----------
class CashHistoryView(TableReport):
    TITLE = "Entradas e saídas por mês"
    HAS_CHART = True
    COLUMNS = [("MÊS", None, False), ("ENTROU", 130, True), ("SAIU", 130, True), ("RESULTADO", 130, True),
               ("ACUMULADO", 130, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.months_box()
        self.period.setCurrentIndex(self.period.findData("12m"))
        self.bar.addWidget(self.period)
        self.finish_bar("O que entrou e saiu de verdade em cada mês (pela data do pagamento; compras no cartão\n"
                        "contam no vencimento da fatura). Transferências entre suas contas não entram.")

    def refresh(self):
        from finora.ui.entries_page import MONTHS
        months = reports.period_months(self.period.currentData())
        with Session() as s:
            data = reports.cash_history(s, self.profile.id, months)
        from finora.ui.report_charts import ChartData
        many = len({r.year for r in data}) > 1
        self.chart = ChartData("bars", [self.month_title(r.year, r.month, many) for r in data],
                               [("Entrou", [r.inflow for r in data]), ("Saiu", [r.outflow for r in data])],
                               self.profile.currency)
        rows, acc = [], Decimal(0)
        for r in data:
            acc += r.result
            rows.append({"cells": [f"{MONTHS[r.month - 1].capitalize()} de {r.year}", r.inflow or None,
                                   -r.outflow if r.outflow else None, r.result, acc],
                         "tones": {1: "pos", 3: "neg" if r.result < 0 else "pos", 4: "neg" if acc < 0 else None}})
        self.fill(rows, "Nada pago ou recebido nesse período.")
        inflow = sum((r.inflow for r in data), Decimal(0))
        outflow = sum((r.outflow for r in data), Decimal(0))
        n = len(data) or 1
        self.footer.setText(f"Entrou <b>{self.fmt(inflow)}</b> &nbsp;·&nbsp; Saiu <b>{self.fmt(-outflow)}</b> "
                            f"&nbsp;·&nbsp; Média de sobra por mês <b>{self.fmt((inflow - outflow) / n)}</b>")


# ---------- inadimplência ----------
class OverdueView(TableReport):
    TITLE = "Inadimplência"

    def subtitle(self) -> str:
        return f"Posição em {date.today():%d/%m/%Y}"
    COLUMNS = [("VENC.", 80, False), ("DESCRIÇÃO", None, False), ("CONTATO", 160, False), ("ATRASO", 90, True),
               ("VALOR", 130, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.summary = QLabel(wordWrap=True)
        self.summary.setTextFormat(Qt.RichText)
        self.bar.addWidget(self.summary, 1)
        self.finish_bar("Tudo o que já venceu e não foi pago (você deve) ou não foi recebido (te devem),\n"
                        "com os dias de atraso. Faturas de cartão atrasadas também entram.")

    def refresh(self):
        today = date.today()
        with Session() as s:
            rep = reports.overdue(s, self.profile.id, today)

        def section(title, items, kind):
            if not items:
                return []
            total = sum((i.amount for i in items), Decimal(0))
            out = [{"cells": ["", f"{title} ({len(items)})", "", "", -total if kind == "expense" else total],
                    "bold": True}]
            for i in items:
                target = (("entry", i.entry_id) if i.entry_id else ("statement", i.card_account_id, i.due))
                out.append({"cells": [i.due.strftime("%d/%m/%y"), i.description, i.contact, f"{i.days} dias",
                                      -i.amount if kind == "expense" else i.amount],
                            "tones": {0: "neg", 3: "neg" if i.days > 30 else None,
                                      4: "pos" if kind == "income" else None},
                            "target": target})
            return out

        rows = section("Você deve", rep.payables, "expense") + section("Te devem", rep.receivables, "income")
        self.fill(rows, "Nada atrasado. Tudo em dia!")
        parts = [f"{label}: <b>{self.fmt(v)}</b>" for label, v, n in rep.buckets(rep.payables) if n]
        self.summary.setText(("Você deve, por atraso — " + " &nbsp;·&nbsp; ".join(parts)) if parts else "")
        owe = sum((i.amount for i in rep.payables), Decimal(0))
        owed = sum((i.amount for i in rep.receivables), Decimal(0))
        self.footer.setText(f"Você deve <b>{self.fmt(owe)}</b> &nbsp;·&nbsp; Te devem <b>{self.fmt(owed)}</b>"
                            " &nbsp;·&nbsp; Duplo clique numa linha abre o lançamento ou a fatura.")
        set_tone(self.footer, None)


# ---------- pontualidade (Fase 3.1, do MCC) ----------
def _days(n: int) -> str:
    return "—" if not n else f"{n} dia" + ("s" if n != 1 else "")


class PunctualityView(TableReport):
    TITLE = "Pontualidade"
    COLUMNS = [("CONTATO", None, False), ("QTD.", 55, True), ("EM DIA", 70, True), ("ATRASADOS", 90, True),
               ("MAIOR ATRASO", 105, True), ("MAIOR ANTECIP.", 110, True), ("MÉDIA", 95, True), ("VALOR", 125, True)]

    def subtitle(self) -> str:
        return f"{self.kind.currentText()} · {self.period.currentText()}"

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.kind = QComboBox()
        for k, label in reports.PUNCTUALITY_KINDS.items():
            self.kind.addItem(label, k)
        self.kind.currentIndexChanged.connect(self.refresh)
        self.period = self.period_box()
        self.period.setCurrentIndex(self.period.findData("12m"))
        self.bar.addWidget(self.kind)
        self.bar.addWidget(self.period)
        self.finish_bar("Por contato, quantos dias antes ou depois do vencimento os lançamentos foram pagos\n"
                        "(pela data do pagamento, no período). Média positiva = atrasa; negativa = antecipa.\n"
                        "Recebimentos: como seus clientes te pagam. Pagamentos: como você paga os fornecedores.")

    @staticmethod
    def _average(v: Decimal) -> str:
        if not v:
            return "no dia"
        text = f"{abs(v)}".replace(".", ",").removesuffix(",0")
        return f"{text} d " + ("atraso" if v > 0 else "antes")

    def refresh(self):
        first, last = reports.period_range(self.period.currentData())
        kind = self.kind.currentData()
        with Session() as s:
            data = reports.punctuality(s, self.profile.id, first, last, kind)
        sign = -1 if kind == "expense" else 1

        def row(r: reports.PunctualityRow, bold: bool = False) -> dict:
            return {"cells": [r.contact, r.count, r.on_time, r.late, _days(r.max_late), _days(r.max_early),
                              self._average(r.average), sign * r.amount],
                    "tones": {3: "neg" if r.late else None, 4: "neg" if r.max_late > 30 else None,
                              6: "neg" if r.average > 0 else "pos" if r.average < 0 else None},
                    "bold": bold}

        rows = [row(r) for r in data]
        total = reports.punctuality_total(data)
        if total:
            rows.append(row(total, bold=True))
        self.fill(rows, "Nenhum lançamento pago neste período.")
        self.footer.setText("" if not total else
                            f"{total.count} pago(s) · <b>{total.late_share}%</b> com atraso · maior atraso "
                            f"<b>{_days(total.max_late)}</b>")


# ---------- saldos em uma data (Fase 3.2, do MCC) ----------
class BalancesAtView(TableReport):
    TITLE = "Saldos em uma data"
    COLUMNS = [("CONTA", None, False), ("TIPO", 110, False), ("REALIZADO", 130, True), ("A RECEBER", 120, True),
               ("A PAGAR", 120, True), ("PREVISTO", 130, True)]

    def subtitle(self) -> str:
        return f"Em {self.day.date().toString('dd/MM/yyyy')}"

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.day = QDateEdit(QDate.currentDate(), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.day.dateChanged.connect(self.refresh)
        self.inactive = QCheckBox("Contas inativas")
        self.inactive.toggled.connect(self.refresh)
        self.bar.addWidget(QLabel("Em"))
        self.bar.addWidget(self.day)
        self.bar.addWidget(self.inactive)
        self.finish_bar("Realizado: o que estava em cada conta no fim do dia (pagos e recebidos até a data).\n"
                        "Previsto: o realizado mais o que estava em aberto vencendo até a data (atrasados inclusive).\n"
                        "Cartão aparece, mas fica fora do total: a dívida dele já é a fatura a pagar.")

    def fmt_cur(self, v: Decimal, currency: str) -> Decimal | str:
        return v if currency == self.profile.currency else money.fmt(v, currency)

    def refresh(self):
        q = self.day.date()
        day = date(q.year(), q.month(), q.day())
        with Session() as s:
            rep = reports.balances_at(s, self.profile.id, day, self.inactive.isChecked())
        rows = []
        for r in rep.rows:
            cur = r.currency
            rows.append({"cells": [r.name, accounts.KINDS.get(r.kind, r.kind), self.fmt_cur(r.realized, cur),
                                   self.fmt_cur(r.to_receive, cur) if r.to_receive else None,
                                   self.fmt_cur(-r.to_pay, cur) if r.to_pay else None, self.fmt_cur(r.forecast, cur)],
                         "tones": {2: "neg" if r.realized < 0 else None, 3: "pos", 4: "neg",
                                   5: "neg" if r.forecast < 0 else None},
                         "muted": r.kind == "card" or not r.is_active})
        if rep.rows:
            rows.append({"cells": ["Total (sem cartões)", "", rep.realized, None, None, rep.forecast], "bold": True,
                         "tones": {2: "neg" if rep.realized < 0 else None, 5: "neg" if rep.forecast < 0 else None}})
        self.fill(rows, "Nenhuma conta.")
        note = " · contas em outra moeda convertidas pela cotação da data" if rep.other_currency else ""
        self.footer.setText(f"Realizado <b>{self.fmt(rep.realized)}</b> &nbsp;·&nbsp; Previsto "
                            f"<b>{self.fmt(rep.forecast)}</b>{note}")


# ---------- comparativo de saldos entre duas datas (Fase 3.3, do MCC) ----------
class BalanceCompareView(TableReport):
    TITLE = "Comparativo de saldos"
    COLUMNS = [("CONTA", None, False), ("SALDO INICIAL", 125, True), ("ENTRADAS", 120, True), ("SAÍDAS", 120, True),
               ("SALDO FINAL", 125, True), ("VARIAÇÃO", 125, True), ("%", 70, True)]

    def subtitle(self) -> str:
        return f"{self.first.date().toString('dd/MM/yyyy')} a {self.last.date().toString('dd/MM/yyyy')}"

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        today = QDate.currentDate()
        self.first = QDateEdit(QDate(today.year(), today.month(), 1).addDays(-1), calendarPopup=True,
                               displayFormat="dd/MM/yyyy")
        self.last = QDateEdit(today, calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.inactive = QCheckBox("Contas inativas")
        for w in (self.first, self.last):
            w.dateChanged.connect(self.refresh)
        self.inactive.toggled.connect(self.refresh)
        for w in (QLabel("De"), self.first, QLabel("a"), self.last, self.inactive):
            self.bar.addWidget(w)
        self.finish_bar("Saldo realizado de cada conta no fim de cada data e o que entrou e saiu entre elas\n"
                        "(pela data do pagamento, como no extrato). Transferências entre contas aparecem nas duas\n"
                        "e se anulam no total. Cartão aparece, mas fica fora do total.")

    @staticmethod
    def _day(w: QDateEdit) -> date:
        q = w.date()
        return date(q.year(), q.month(), q.day())

    def refresh(self):
        with Session() as s:
            rep = reports.compare_balances(s, self.profile.id, self._day(self.first), self._day(self.last),
                                           self.inactive.isChecked())
        cols = list(self.COLUMNS)
        cols[1] = (f"SALDO EM {rep.first:%d/%m/%y}", 125, True)
        cols[4] = (f"SALDO EM {rep.last:%d/%m/%y}", 125, True)
        self.set_columns(cols)

        def pct(v: Decimal | None) -> str:
            return "" if v is None else f"{'+' if v > 0 else ''}{v}%".replace(".", ",")

        def tone(v: Decimal) -> str | None:
            return "pos" if v > 0 else "neg" if v < 0 else None

        rows = []
        for r in rep.rows:
            fmt = (lambda v, c=r.currency: v if c == self.profile.currency else money.fmt(v, c))
            rows.append({"cells": [r.name, fmt(r.start), fmt(r.inflow) if r.inflow else None,
                                   fmt(-r.outflow) if r.outflow else None, fmt(r.end), fmt(r.change),
                                   pct(r.change_pct)],
                         "tones": {2: "pos", 3: "neg", 5: tone(r.change), 6: tone(r.change)},
                         "muted": r.kind == "card" or not r.is_active})
        if rep.rows:
            rows.append({"cells": ["Total (sem cartões)", rep.start, rep.inflow or None, -rep.outflow or None, rep.end,
                                   rep.change, ""], "bold": True, "tones": {5: tone(rep.change)}})
        self.fill(rows, "Nenhuma conta.")
        note = " · outra moeda convertida pela cotação de cada data" if rep.other_currency else ""
        self.footer.setText(f"Variação no período <b>{self.fmt(rep.change)}</b>{note}")


# ---------- extrato de fechamento de caixa (Fase 3.4, do MCC) ----------
class CashClosingView(TableReport):
    TITLE = "Fechamento de caixa"
    COLUMNS = [("DATA", 70, False), ("CONTA", 130, False), ("DESCRIÇÃO", None, False), ("CATEGORIA", 160, False),
               ("ENTRADA", 115, True), ("SAÍDA", 115, True), ("ACUMULADO", 130, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.period = self.period_box()
        self.internal = QCheckBox("Transferências entre contas")
        self.internal.setToolTip("Mostra também o dinheiro que só trocou de conta (não muda o acumulado)")
        self.internal.toggled.connect(self.refresh)
        self.bar.addWidget(self.period)
        self.bar.addWidget(self.internal)
        self.finish_bar("Tudo o que entrou e saiu de todas as contas de dinheiro no período (bancos e caixa,\n"
                        "sem cartões), na data do pagamento, com o saldo acumulado de todas juntas.\n"
                        "Pagar a fatura do cartão sai do caixa e aparece aqui.")

    def refresh(self):
        first, last = reports.period_range(self.period.currentData())
        with Session() as s:
            rep = reports.cash_closing(s, self.profile.id, first, last, self.internal.isChecked())
        rows = [{"cells": [first.strftime("%d/%m"), "", "Saldo anterior (todas as contas)", "", None, None, rep.opening],
                 "bold": True, "tones": {6: "neg" if rep.opening < 0 else None}}]
        for line in rep.lines:
            rows.append({"cells": [line.day.strftime("%d/%m"), line.account, line.description, line.category,
                                   line.inflow or None, -line.outflow if line.outflow else None,
                                   None if line.internal else line.balance],
                         "tones": {4: "pos", 6: "neg" if line.balance < 0 else None},
                         "muted": line.internal, "target": ("entry", line.entry_id)})
        self.fill(rows, "")
        note = " · outra moeda convertida pela cotação do dia" if rep.other_currency else ""
        self.footer.setText(f"Entradas <b>{self.fmt(rep.inflow)}</b> &nbsp;·&nbsp; Saídas <b>{self.fmt(-rep.outflow)}</b>"
                            f" &nbsp;·&nbsp; Saldo final <b>{self.fmt(rep.closing)}</b>{note}")


# ---------- demonstrativo anual (Fase 3.6, do MCC) ----------
class AnnualView(CategoryMonthsView):
    TITLE = "Demonstrativo anual"

    def subtitle(self) -> str:
        return f"{self.year.currentText()} · por {self.group_by.currentText().lower()}"

    def __init__(self, profile: Profile, t: dict):
        TableReport.__init__(self, profile, t)
        this = date.today().year
        self.year = QComboBox()
        for y in range(this + 1, this - 7, -1):
            self.year.addItem(str(y), y)
        self.year.setCurrentIndex(self.year.findData(this))
        self.group_by = QComboBox()
        for k, (label, _missing) in reports.GROUP_BY.items():
            self.group_by.addItem(label, k)
        for w in (self.year, self.group_by):
            w.currentIndexChanged.connect(self.refresh)
            self.bar.addWidget(w)
        self.finish_bar("Os 12 meses do ano escolhido, com a média mensal e o total, agrupados por categoria,\n"
                        "contato, centro de custo ou conta (pela data da compra/vencimento, pago ou não).\n"
                        "É o demonstrativo anual de despesas e receitas do MCC.")

    def _months(self) -> list[tuple[int, int]]:
        y = self.year.currentData()
        return [(y, m) for m in range(1, 13)]

    def _by(self) -> str:
        return self.group_by.currentData()

    def _label(self, r) -> str:
        return super()._label(r) if self._by() == "category" else r.category


# ---------- orçamento por centro de custo / projeção por centro de lucro (Fase 3.7, do MCC) ----------
class CenterTargetsView(TableReport):
    TITLE = "Metas por centro"
    COLUMNS = [("CENTRO", None, False), ("META MENSAL", 115, True), ("META NO PERÍODO", 130, True),
               ("LANÇADO", 125, True), ("% ATINGIDO", 95, True), ("FALTA", 125, True)]

    def subtitle(self) -> str:
        return f"{self.kind.currentText()} · {self.period.currentText()}" + \
            (" · só pagos" if self.paid_only.isChecked() else "")

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.kind = QComboBox()
        for k, label in reports.TARGET_KINDS.items():
            self.kind.addItem(label, k)
        self.paid_only = QCheckBox("Só pagos")
        self.paid_only.setToolTip("Conta só o que já foi pago ou recebido (sem os em aberto)")
        self.period = self.period_box()
        self.period.setCurrentIndex(self.period.findData("ytd"))
        self.kind.currentIndexChanged.connect(self.refresh)
        self.paid_only.toggled.connect(self.refresh)
        for w in (self.kind, self.period, self.paid_only):
            self.bar.addWidget(w)
        self.finish_bar("Orçamento: as despesas de cada centro de custo contra o orçamento mensal dele.\n"
                        "Projeção: as receitas de cada centro de lucro contra a projeção mensal.\n"
                        "Meta no período = meta mensal x meses do período. A meta é cadastrada em Centros de custo.")

    def refresh(self):
        first, last = reports.period_range(self.period.currentData())
        kind = self.kind.currentData()
        with Session() as s:
            data = reports.center_targets(s, self.profile.id, first, last, kind, self.paid_only.isChecked())
        self.set_columns([c if i != 3 else ("PAGO" if self.paid_only.isChecked() else "LANÇADO", 125, True)
                          for i, c in enumerate(self.COLUMNS)])
        rows = []
        for r in data:
            pct = "" if r.pct is None else f"{r.pct}%".replace(".", ",")
            over = r.left is not None and r.left < 0
            good = (not over) if kind == "expense" else (r.pct is not None and r.pct >= 100)
            rows.append({"cells": [r.name, r.monthly, r.target, r.actual, pct, r.left],
                         "tones": {4: ("pos" if good else "neg") if r.pct is not None else None,
                                   5: "neg" if over and kind == "expense" else None},
                         "muted": r.monthly is None})
        empty = ("Nenhum centro de custo para despesas." if kind == "expense" else
                 "Nenhum centro de lucro (centro que vale para receitas).")
        self.fill(rows, empty + "\nCadastre em Centros de custo, com o orçamento ou a projeção mensal.")
        target = sum((r.target for r in data if r.target is not None), Decimal(0))
        actual = sum((r.actual for r in data if r.target is not None), Decimal(0))
        pct = "" if not target else f" ({(100 * actual / target).quantize(Decimal('0.1'))}%)".replace(".", ",")
        self.footer.setText(f"Meta no período <b>{self.fmt(target)}</b> &nbsp;·&nbsp; Lançado nos centros com meta "
                            f"<b>{self.fmt(actual)}</b>{pct}")
