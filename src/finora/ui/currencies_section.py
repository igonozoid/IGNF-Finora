"""Configurações › Moedas: cotações das moedas usadas nas contas (manual ou PTAX do Banco Central)."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDateEdit, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.core.logs import log
from finora.services import fx
from finora.ui import theme
from finora.ui.widgets import button, field_label, icon_label, set_tone, upgrade_box

LOCK_MSG = ("Contas em outras moedas, com cotação por data (inclusive a PTAX do Banco Central), são recursos "
            "das edições Plus e Pro.")
R = Qt.AlignRight | Qt.AlignVCenter
SOURCES = {"manual": "Digitada", "bcb": "Banco Central (PTAX)"}


def _rate_text(v: Decimal) -> str:
    """5.43210000 -> '5,4321' (até 6 casas, sem zeros sobrando)."""
    txt = f"{v.normalize():f}"
    if "." in txt:
        whole, frac = txt.split(".")
        txt = whole + "," + frac[:6]
    return txt


def _table_height(tv: QTableWidget, rows: int) -> int:
    """Altura exata para `rows` linhas + cabeçalho (sem barra de rolagem nem sobra)."""
    return tv.horizontalHeader().sizeHint().height() + rows * theme.ROW_H + 2 * tv.frameWidth()


class CurrenciesSection(QFrame):
    message = Signal(str)
    changed = Signal()             # cotações mudaram: os valores em moeda principal foram recalculados

    def __init__(self, entity_id: int, base: str, t: dict, max_w: int):
        super().__init__(objectName="card")
        self.entity_id, self.base, self.t = entity_id, base, t
        self.setMaximumWidth(max_w)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, theme.SP_L, 14, 14)
        lay.setSpacing(theme.SP_M)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(icon_label("fa6s.coins", t, "acc", 12))
        head.addWidget(QLabel("Moedas e cotações", objectName="sectionTitle"))
        head.addStretch(1)
        lay.addLayout(head)
        self.intro = QLabel(wordWrap=True)
        self.intro.setProperty("role", "muted")
        lay.addWidget(self.intro)
        self.locked = not allowed(current_edition(), "multi_currency")
        if self.locked:
            self.intro.setText(f"Sua moeda principal é {base}. Todas as contas usam essa moeda.")
            lay.addWidget(upgrade_box(LOCK_MSG, t, self, compact=True))
            return

        self.warn = QLabel(wordWrap=True)
        set_tone(self.warn, "neg")
        lay.addWidget(self.warn)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["MOEDA", "CONTAS", "COTAÇÃO", "DESDE", "FONTE"])
        for tv in (self.table,):
            tv.verticalHeader().hide()
            tv.verticalHeader().setDefaultSectionSize(theme.ROW_H)
            tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tv.setSelectionBehavior(QAbstractItemView.SelectRows)
            tv.setSelectionMode(QAbstractItemView.SingleSelection)
            tv.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        hdr.setHighlightSections(False)
        lay.addWidget(self.table)

        # nova cotação
        form = QHBoxLayout()
        form.setSpacing(theme.SP_S)
        self.currency = QComboBox()
        self._fill_currencies()
        self.day = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.day.setDate(QDate.currentDate())
        self.day.setFont(theme.mono_font())
        self.rate = QLineEdit(placeholderText="Ex.: 5,4321")
        self.rate.setFont(theme.mono_font())
        self.rate.setAlignment(Qt.AlignRight)
        self.rate.setMaximumWidth(110)
        self.save_btn = button("Salvar cotação", "secondary")
        self.bcb_btn = button("Buscar no Banco Central", "link", t, "fa6s.cloud-arrow-down", "acc")
        self.bcb_btn.setToolTip("Cotação PTAX de venda do dia (ou do último dia útil antes dele).")
        self.bcb_btn.setVisible(base == "BRL")
        form.addWidget(self.currency, 1)
        form.addWidget(self.day)
        form.addWidget(self.rate)
        form.addWidget(self.save_btn)
        lay.addWidget(field_label(f"Nova cotação — quanto vale 1 unidade em {base}", t,
                                  "Vale a partir da data escolhida, até a próxima cotação cadastrada.\n"
                                  "Lançamentos nessa moeda são convertidos pela cotação da data deles."))
        lay.addLayout(form)
        links = QHBoxLayout()
        links.addWidget(self.bcb_btn)
        self.other_btn = button("Cadastrar outra moeda…", "link", t, "fa6s.plus", "acc")
        self.other_btn.setToolTip("Para moedas que não estão na lista (ex.: rand sul-africano, ZAR)")
        links.addWidget(self.other_btn)
        links.addStretch(1)
        lay.addLayout(links)
        self.other_btn.clicked.connect(self._other_currency)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)

        # histórico da moeda escolhida
        self.hist_lbl = field_label("Histórico", t)
        lay.addWidget(self.hist_lbl)
        self.history = QTableWidget(0, 3)
        self.history.setHorizontalHeaderLabels(["DATA", "COTAÇÃO", "FONTE"])
        self.history.verticalHeader().hide()
        self.history.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history.setShowGrid(False)
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.history)
        self.del_btn = button("Excluir cotação selecionada", "link")
        lay.addWidget(self.del_btn, 0, Qt.AlignLeft)

        self.save_btn.clicked.connect(self._save)
        self.rate.returnPressed.connect(self._save)
        self.bcb_btn.clicked.connect(self._fetch)
        self.del_btn.clicked.connect(self._delete)
        self.currency.currentIndexChanged.connect(self._fill_history)
        self.table.cellClicked.connect(self._pick_row)
        self.refresh()

    def _fill_currencies(self):
        keep = self.currency.currentData()
        self.currency.blockSignals(True)
        self.currency.clear()
        for code, (_sym, label) in money.CURRENCIES.items():
            if code != self.base:
                self.currency.addItem(f"{code} — {label}", code)
        self.currency.setCurrentIndex(max(0, self.currency.findData(keep)))
        self.currency.blockSignals(False)

    def set_base(self, base: str):
        """A moeda principal mudou em Perfil."""
        self.base = base
        if self.locked:
            self.intro.setText(f"Sua moeda principal é {base}. Todas as contas usam essa moeda.")
            return
        self._fill_currencies()
        self.bcb_btn.setVisible(base == "BRL")
        self.refresh()

    # ----- dados -----
    def refresh(self):
        if self.locked:
            return
        with Session() as s:
            st = fx.status(s, self.entity_id)
        self._status = st
        self.intro.setText(f"Moeda principal: {self.base}. Contas em outra moeda guardam o valor na moeda delas; "
                           f"relatórios, Dashboard e orçamento somam tudo em {self.base}, pela cotação da data de "
                           "cada lançamento.")
        self.table.setRowCount(len(st))
        for r, c in enumerate(st):
            cells = [f"{c.currency} — {money.CURRENCIES.get(c.currency, ('', c.currency))[1]}", str(c.accounts),
                     f"{money.symbol(self.base)} {_rate_text(c.latest.rate)}" if c.latest else "sem cotação",
                     c.latest.day.strftime("%d/%m/%Y") if c.latest else "—",
                     SOURCES.get(c.latest.source, c.latest.source) if c.latest else "—"]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if col in (1, 2):
                    it.setTextAlignment(R)
                if col == 2:
                    it.setFont(theme.mono_font())
                self.table.setItem(r, col, it)
        self.table.setVisible(bool(st))
        self.table.setFixedHeight(_table_height(self.table, len(st)) if st else 0)
        missing = [c for c in st if c.latest is None and c.accounts]
        self.warn.setText(" ".join(f"{c.currency} está sem cotação: o saldo e os lançamentos dessa moeda contam "
                                   f"1 para 1 em {self.base} até você cadastrar uma." for c in missing))
        self.warn.setVisible(bool(missing))
        self._fill_history()

    def _pick_row(self, row: int, _col: int):
        if row < len(self._status):
            self.currency.setCurrentIndex(max(0, self.currency.findData(self._status[row].currency)))

    def _fill_history(self):
        cur = self.currency.currentData()
        with Session() as s:
            self._rates = fx.list_rates(s, self.entity_id, cur, limit=24) if cur else []
        self.hist_lbl.label.setText(f"Histórico de {cur}" if cur else "Histórico")
        self.history.setRowCount(len(self._rates))
        for r, rv in enumerate(self._rates):
            for col, text in enumerate((rv.day.strftime("%d/%m/%Y"), _rate_text(rv.rate),
                                        SOURCES.get(rv.source, rv.source))):
                it = QTableWidgetItem(text)
                if col == 1:
                    it.setTextAlignment(R)
                    it.setFont(theme.mono_font())
                self.history.setItem(r, col, it)
        self.history.setVisible(bool(self._rates))
        self.history.setFixedHeight(_table_height(self.history, min(len(self._rates), 6)))
        self.del_btn.setVisible(bool(self._rates))

    # ----- ações -----
    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def _store(self, cur: str, day: date, rate: Decimal, source: str):
        with Session() as s:
            fx.set_rate(s, self.entity_id, cur, day, rate, source)
        log.info("Cotação %s em %s: %s (%s)", cur, day, rate, source)
        self._error(None)
        self.rate.clear()
        self.refresh()
        self.changed.emit()
        self.message.emit(f"Cotação de {cur} em {day:%d/%m/%Y}: {money.symbol(self.base)} {_rate_text(rate)}. "
                          "Valores recalculados.")

    def _save(self):
        try:
            text = self.rate.text().strip().replace(".", ",")
            rate = Decimal(text.replace(",", ".")) if text else None
        except ArithmeticError:
            rate = None
        if rate is None or rate <= 0:
            self._error("Digite a cotação, por exemplo 5,4321.")
            return
        try:
            self._store(self.currency.currentData(), self.day.date().toPython(), rate, "manual")
        except ValueError as e:
            self._error(str(e))

    def _other_currency(self):
        dlg = OtherCurrencyDialog(self, self.t)
        dlg.exec()
        if dlg.changed:
            self._fill_currencies()
            self.refresh()
            self.message.emit("Moedas atualizadas. As novas já aparecem nas listas de moeda.")

    def _fetch(self):
        cur, day = self.currency.currentData(), self.day.date().toPython()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            when, rate = fx.fetch_bcb(cur, day)
        except ValueError as e:
            self._error(str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._store(cur, when, rate, "bcb")

    def _delete(self):
        row = self.history.currentRow()
        if not 0 <= row < len(self._rates):
            self._error("Escolha no histórico a cotação que quer excluir.")
            return
        with Session() as s:
            fx.delete_rate(s, self._rates[row].id)
        self.refresh()
        self.changed.emit()
        self.message.emit("Cotação excluída. Valores recalculados.")

    def apply_theme(self, t: dict):
        self.t = t


class OtherCurrencyDialog(QDialog):
    """Cadastrar (ou remover) uma moeda que não está na lista do Finora."""

    def __init__(self, parent, t: dict):
        super().__init__(parent)
        from finora.services import currencies
        self.changed = False
        self.setObjectName("wizard")
        self.setWindowTitle("Outras moedas")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        intro = QLabel("Use para uma moeda que não está na lista. O código tem 3 letras (padrão internacional "
                       "ISO 4217, ex.: ZAR); o símbolo aparece nos valores. A cotação é digitada à mão.",
                       wordWrap=True)
        intro.setProperty("role", "muted")
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.code = QLineEdit(maxLength=3, placeholderText="ZAR")
        self.code.setMaximumWidth(70)
        self.symbol = QLineEdit(maxLength=6, placeholderText="R")
        self.symbol.setMaximumWidth(80)
        self.name = QLineEdit(maxLength=60, placeholderText="Rand sul-africano")
        add = button("Cadastrar", "primary")
        for w in (self.code, self.symbol, self.name):
            row.addWidget(w)
        row.addWidget(add)
        lay.addLayout(row)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        lay.addWidget(field_label("Cadastradas", t))
        self.list = QTableWidget(0, 3)
        self.list.setHorizontalHeaderLabels(["CÓDIGO", "SÍMBOLO", "NOME"])
        self.list.verticalHeader().hide()
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.list)
        bottom = QHBoxLayout()
        remove = button("Remover selecionada", "link")
        close = button("Fechar", "secondary")
        bottom.addWidget(remove)
        bottom.addStretch(1)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        add.clicked.connect(self.add)
        self.name.returnPressed.connect(self.add)
        remove.clicked.connect(self.remove)
        close.clicked.connect(self.accept)
        self._svc = currencies
        self.refresh()

    def refresh(self):
        with Session() as s:
            rows = [(c.code, c.symbol, c.name) for c in self._svc.list_custom(s)]
        self.list.setRowCount(len(rows))
        for r, cells in enumerate(rows):
            for c, text in enumerate(cells):
                self.list.setItem(r, c, QTableWidgetItem(text))

    def _err(self, text: str | None):
        self.error.setText(text or "")
        self.error.setVisible(bool(text))

    def add(self):
        try:
            with Session() as s:
                self._svc.add(s, self.code.text(), self.symbol.text(), self.name.text())
        except ValueError as e:
            self._err(str(e))
            return
        self._err(None)
        self.changed = True
        for w in (self.code, self.symbol, self.name):
            w.clear()
        self.refresh()

    def remove(self):
        r = self.list.currentRow()
        if r < 0:
            return
        code = self.list.item(r, 0).text()
        try:
            with Session() as s:
                self._svc.remove(s, code)
        except ValueError as e:
            self._err(str(e))
            return
        self._err(None)
        self.changed = True
        self.refresh()
