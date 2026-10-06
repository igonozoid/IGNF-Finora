"""Relatórios em lista: extrato por conta, por categoria, por contato e inadimplência."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, reports
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
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        for i, (_title, width, is_value) in enumerate(self.COLUMNS):
            if width is None:
                hdr.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.Fixed)
                hdr.resizeSection(i, width)
            if is_value:
                self.table.horizontalHeaderItem(i).setTextAlignment(R)
        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.footer = QLabel(wordWrap=True)
        self.footer.setTextFormat(Qt.RichText)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(10)
        self.lay.addLayout(self.bar)
        self.lay.addWidget(self.table, 1)
        self.lay.addWidget(self.empty, 1)
        self.lay.addWidget(self.footer)
        self._targets: list = []
        self.table.cellDoubleClicked.connect(self._double)

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
        self.bar.addStretch(1)
        self.bar.addLayout(export_buttons(self, self.t))

    # ----- tabela -----
    def fill(self, rows: list[dict], empty_text: str):
        """rows: {"cells": [...], "tones": {col: tone}, "bold": bool, "muted": bool, "target": (tipo, ...)}"""
        self.table.setRowCount(len(rows))
        self._targets = []
        bold = QFont()
        bold.setBold(True)
        for r, row in enumerate(rows):
            self._targets.append(row.get("target"))
            for c, text in enumerate(row["cells"]):
                item = QTableWidgetItem(text)
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

    def apply_theme(self, t: dict):
        self.t = t


# ---------- extrato por conta ----------
class AccountStatementView(TableReport):
    COLUMNS = [("DATA", 70, False), ("DESCRIÇÃO", None, False), ("CATEGORIA", 170, False),
               ("ENTRADA", 120, True), ("SAÍDA", 120, True), ("SALDO", 130, True)]

    def __init__(self, profile: Profile, t: dict):
        super().__init__(profile, t)
        self.account = QComboBox()
        self.account.setMinimumWidth(160)
        self.account.currentIndexChanged.connect(self.refresh)
        self.period = self.period_box()
        self.bar.addWidget(self.account)
        self.bar.addWidget(self.period)
        self.finish_bar("Tudo o que entrou e saiu da conta no período, na data em que aconteceu,\n"
                        "com o saldo depois de cada movimento. Só o que já foi pago/recebido.\n"
                        "No cartão, as compras aparecem na data da compra.")

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
            st = reports.account_statement(s, acc_id, first, last)
        rows = [{"cells": [first.strftime("%d/%m"), "Saldo anterior", "", "", "", self.fmt(st.opening)],
                 "bold": True, "tones": {5: "neg" if st.opening < 0 else None}}]
        for line in st.lines:
            rows.append({"cells": [line.day.strftime("%d/%m"), line.description, line.category,
                                   self.fmt(line.inflow) if line.inflow else "",
                                   self.fmt(-line.outflow) if line.outflow else "", self.fmt(line.balance)],
                         "tones": {3: "pos", 1: None, 5: "neg" if line.balance < 0 else None},
                         "target": ("entry", line.entry_id)})
        self.fill(rows, "")
        self.footer.setText(f"Entradas <b>{self.fmt(st.inflow)}</b> &nbsp;·&nbsp; Saídas <b>{self.fmt(-st.outflow)}</b>"
                            f" &nbsp;·&nbsp; Saldo final <b>{self.fmt(st.closing)}</b>")


# ---------- por categoria ----------
class ByCategoryView(TableReport):
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
        rows = []
        for r in data:
            label = r.category if r.group == r.category else f"{r.group} › {r.category}"
            share = (r.total * 100 / totals[r.kind]) if totals[r.kind] else Decimal(0)
            rows.append({"cells": [label, "Receita" if r.kind == "income" else "Despesa", str(r.count),
                                   self.fmt(r.total if r.kind == "income" else -r.total),
                                   f"{share:.1f}%".replace(".", ",")],
                         "tones": {3: "pos" if r.kind == "income" else None}})
        self.fill(rows, "Nenhum lançamento com categoria neste período.")
        self.footer.setText(f"Receitas <b>{self.fmt(totals['income'])}</b> &nbsp;·&nbsp; "
                            f"Despesas <b>{self.fmt(-totals['expense'])}</b>")


# ---------- por contato ----------
class ByContactView(TableReport):
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
        rows = [{"cells": [r.contact, str(r.count), self.fmt(r.received) if r.received else "",
                           self.fmt(-r.paid) if r.paid else "", self.fmt(r.received - r.paid)],
                 "tones": {2: "pos", 4: "neg" if r.received < r.paid else "pos" if r.received > r.paid else None}}
                for r in data]
        self.fill(rows, "Nenhum lançamento com contato neste período.")
        rec = sum((r.received for r in data), Decimal(0))
        paid = sum((r.paid for r in data), Decimal(0))
        self.footer.setText(f"Recebido <b>{self.fmt(rec)}</b> &nbsp;·&nbsp; Pago <b>{self.fmt(-paid)}</b>")


# ---------- inadimplência ----------
class OverdueView(TableReport):
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
            out = [{"cells": ["", f"{title} ({len(items)})", "", "", self.fmt(-total if kind == "expense" else total)],
                    "bold": True}]
            for i in items:
                target = (("entry", i.entry_id) if i.entry_id else ("statement", i.card_account_id, i.due))
                out.append({"cells": [i.due.strftime("%d/%m/%y"), i.description, i.contact, f"{i.days} dias",
                                      self.fmt(-i.amount if kind == "expense" else i.amount)],
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
