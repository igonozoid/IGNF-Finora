"""Faturas do cartão de crédito: lista, compras de cada fatura e pagamento."""
from datetime import date

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.core.logs import log
from finora.models import Account
from finora.services import accounts, cards
from finora.ui import theme
from finora.ui.widgets import button, field_label, set_tone

TONES = {"late": "neg", "paid": "pos", "open": None, "closed": None, "empty": "mut", "future": "mut"}


def _mono(widget):
    widget.setFont(theme.mono_font())
    return widget


class PayDialog(QDialog):
    """Pagar a fatura (toda ou parte), saindo de uma conta que não seja cartão."""

    def __init__(self, parent, st: cards.Statement, currency: str, entity_id: int, t: dict):
        super().__init__(parent)
        self.st, self.currency = st, currency
        self.setObjectName("wizard")
        self.setWindowTitle(f"Pagar fatura {st.account} {st.label}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(QLabel(f"Fatura {st.account} {st.label} · vence {st.due:%d/%m/%Y}", objectName="sectionTitle"))
        lay.addWidget(QLabel(f"Falta pagar {money.fmt(st.remaining, currency)}"))

        self.source = QComboBox()
        with Session() as s:
            for a in accounts.list_accounts(s, entity_id):
                if a.kind != "card":
                    self.source.addItem(f"{a.name} ({money.fmt(a.balance, a.currency)})", a.id)
        self.amount = _mono(QLineEdit(money.fmt(st.remaining, currency).split(" ", 1)[1]))
        self.amount.setAlignment(Qt.AlignRight)
        self.when = _mono(QDateEdit(QDate.currentDate(), calendarPopup=True, displayFormat="dd/MM/yyyy"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP_M)
        grid.setVerticalSpacing(3)
        grid.addWidget(field_label("Sai da conta", t), 0, 0, 1, 2)
        grid.addWidget(self.source, 1, 0, 1, 2)
        grid.addWidget(field_label("Valor", t, "Pode pagar só uma parte; o que faltar continua em aberto."), 2, 0)
        grid.addWidget(field_label("Data do pagamento", t), 2, 1)
        grid.addWidget(self.amount, 3, 0)
        grid.addWidget(self.when, 3, 1)
        lay.addLayout(grid)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancelar", "secondary")
        ok = button("Pagar", "primary")
        ok.setDefault(True)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._pay)
        if self.source.count() == 0:
            self._err("Cadastre uma conta (banco ou carteira) para pagar a fatura.")
            ok.setEnabled(False)

    def _err(self, msg):
        self.error.setText(msg)
        self.error.show()

    def _pay(self):
        try:
            value = money.parse(self.amount.text())
        except ValueError:
            self._err("Valor inválido. Use o formato 1.234,56.")
            return
        try:
            with Session() as s:
                cards.pay(s, self.st.account_id, self.st.due, from_account_id=self.source.currentData(),
                          amount=value, when=self.when.date().toPython())
        except ValueError as e:
            self._err(str(e))
            return
        log.info("Fatura paga (cartão %s, vencimento %s)", self.st.account_id, self.st.due)
        self.accept()


class StatementsDialog(QDialog):
    def __init__(self, parent, account_id: int, currency: str, t: dict, select_due: date | None = None):
        super().__init__(parent)
        self.account_id, self.currency, self.t = account_id, currency, t
        self.changed = False          # houve pagamento? (quem abriu atualiza a tela)
        self._sts: list[cards.Statement] = []
        self.setObjectName("wizard")
        self.resize(860, 540)
        self.setMinimumSize(640, 420)

        self.info = QLabel()
        self.info.setProperty("role", "muted")
        self.list = QListWidget(objectName="statementList")
        self.list.setFixedWidth(240)

        self.title = QLabel(objectName="wizardTitle")
        self.summary = QGridLayout()
        self.summary.setHorizontalSpacing(18)
        self.summary.setVerticalSpacing(2)
        self.vals = {}
        for i, key in enumerate(("Fecha em", "Vence em", "Total", "Pago", "Falta pagar")):
            lbl = QLabel(key)
            lbl.setProperty("role", "field")
            val = _mono(QLabel())
            self.summary.addWidget(lbl, 0, i)
            self.summary.addWidget(val, 1, i)
            self.vals[key] = val
        self.status = QLabel()
        self.pay_btn = button("Pagar fatura", "primary", t, "fa6s.money-bill-wave", "on_acc")

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["COMPRA", "DESCRIÇÃO", "CATEGORIA", "VALOR"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        for col, w in ((0, 70), (2, 150), (3, 110)):
            hdr.resizeSection(col, w)
        self.empty = QLabel("Nenhuma compra nesta fatura.", alignment=Qt.AlignCenter)
        self.empty.setProperty("role", "muted")

        right = QVBoxLayout()
        right.setSpacing(theme.SP_M)
        head = QHBoxLayout()
        head.addWidget(self.title)
        head.addWidget(self.status)
        head.addStretch(1)
        head.addWidget(self.pay_btn)
        right.addLayout(head)
        right.addLayout(self.summary)
        right.addWidget(self.table, 1)
        right.addWidget(self.empty, 1)

        body = QHBoxLayout()
        body.setSpacing(theme.SP_L)
        body.addWidget(self.list)
        body.addLayout(right, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = button("Fechar", "secondary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(self.info)
        lay.addLayout(body, 1)
        lay.addLayout(footer)

        self.list.currentRowChanged.connect(self._show)
        self.pay_btn.clicked.connect(self._pay)
        self._load(select_due)

    def _load(self, select_due: date | None = None):
        today = date.today()
        with Session() as s:
            acc = s.get(Account, self.account_id)
            self.entity_id = acc.entity_id
            self.setWindowTitle(f"Faturas · {acc.name}")
            self._sts = cards.list_statements(s, self.account_id, today, back=12)
            free = cards.available_limit(s, self.account_id)
            bits = [f"Fecha dia {acc.closing_day} · vence dia {acc.due_day}"]
            if acc.credit_limit is not None:
                bits.append(f"Limite {money.fmt(acc.credit_limit, self.currency)} · "
                            f"disponível {money.fmt(free, self.currency)}")
            self.info.setText("   ·   ".join(bits))
        current_due = select_due or next((st.due for st in reversed(self._sts) if st.status(today) != "paid"
                                          and st.due >= today), None)
        self.list.blockSignals(True)
        self.list.clear()
        pick = 0
        for i, st in enumerate(self._sts):
            it = QListWidgetItem(self.list)
            it.setSizeHint(QSize(0, 44))
            self.list.setItemWidget(it, self._row(st, today))
            if st.due == current_due:
                pick = i
        self.list.blockSignals(False)
        if self._sts:
            self.list.setCurrentRow(pick)
            self._show(pick)

    def _row(self, st: cards.Statement, today: date) -> QWidget:
        w = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setHorizontalSpacing(theme.SP_M)
        lay.setVerticalSpacing(0)
        name = QLabel(st.label.capitalize(), objectName="cardTitle")
        due = QLabel(f"vence {st.due:%d/%m}")
        due.setProperty("role", "field")
        total = _mono(QLabel(money.fmt(st.charges, self.currency)))
        status = QLabel(st.status_label(today))
        status.setProperty("role", "field")
        set_tone(status, TONES[st.status(today)])
        lay.addWidget(name, 0, 0)
        lay.addWidget(total, 0, 1, Qt.AlignRight)
        lay.addWidget(due, 1, 0)
        lay.addWidget(status, 1, 1, Qt.AlignRight)
        return w

    def _show(self, row: int):
        if not 0 <= row < len(self._sts):
            return
        st, today = self._sts[row], date.today()
        self.current = st
        self.title.setText(f"Fatura {st.label}")
        self.status.setText(st.status_label(today))
        set_tone(self.status, TONES[st.status(today)])
        cur = self.currency
        for key, value in (("Fecha em", st.closing.strftime("%d/%m/%Y")), ("Vence em", st.due.strftime("%d/%m/%Y")),
                           ("Total", money.fmt(st.charges, cur)), ("Pago", money.fmt(st.paid, cur)),
                           ("Falta pagar", money.fmt(st.remaining, cur))):
            self.vals[key].setText(value)
        set_tone(self.vals["Falta pagar"], "neg" if st.status(today) == "late" else None)
        self.pay_btn.setVisible(st.remaining > 0)
        self.pay_btn.setToolTip("A fatura ainda está aberta: dá para pagar antes de fechar." if
                                st.status(today) == "open" else "")
        with Session() as s:
            items = cards.statement_entries(s, self.account_id, st.due)
        self.table.setRowCount(len(items))
        for r, e in enumerate(items):
            desc = e.description + (f"  ({e.installment})" if e.installment else "")
            refund = e.kind == "income"
            cells = [(e.competence_date or e.due_date).strftime("%d/%m"), desc,
                     ("Estorno" if refund else e.category or "Sem categoria"),
                     money.fmt(e.amount if refund else -e.amount, cur)]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c in (0, 3):
                    item.setFont(theme.mono_font())
                if c == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.setVisible(bool(items))
        self.empty.setVisible(not items)

    def _pay(self):
        dlg = PayDialog(self, self.current, self.currency, self.entity_id, self.t)
        if dlg.exec() == QDialog.Accepted:
            self.changed = True
            self._load(self.current.due)


def open_statements(parent, account_id: int, currency: str, t: dict, select_due: date | None = None) -> bool:
    """Abre a janela de faturas. Retorna True se alguma fatura foi paga (para atualizar a tela)."""
    dlg = StatementsDialog(parent, account_id, currency, t, select_due)
    dlg.exec()
    return dlg.changed
