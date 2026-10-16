"""Janela de baixa (FBaixa do MCC): data do pagamento, valor que de fato saiu ou entrou (juros, multa,
desconto), a conta usada e uma observação."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QComboBox, QDateEdit, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, entries
from finora.services.entries import EntryView
from finora.ui import theme
from finora.ui.widgets import button, field_label

TITLES = {"expense": "Pagar", "income": "Receber", "transfer": "Marcar transferência como feita",
          "deposit": "Marcar depósito como feito", "withdrawal": "Marcar retirada como feita"}


class PaymentDialog(QDialog):
    def __init__(self, parent, e: EntryView, t: dict, today: date | None = None):
        super().__init__(parent)
        self.entry = e
        self.paid = False
        self.setObjectName("wizard")
        self.setWindowTitle(TITLES[e.kind])
        self.setMinimumWidth(380)
        transfer = e.kind in entries.NO_CATEGORY      # transferência e ajuste: só a data
        today = today or date.today()

        info = QLabel(f"<b>{e.description}</b>{f' ({e.installment})' if e.installment else ''}<br>"
                      f"Vence em {e.due_date:%d/%m/%Y} · previsto {money.fmt(e.amount, e.currency)}", wordWrap=True)
        info.setTextFormat(Qt.RichText)
        self.when = QDateEdit(QDate(today.year, today.month, today.day), calendarPopup=True,
                              displayFormat="dd/MM/yyyy")
        self.when.setFont(theme.mono_font())
        self.amount = QLineEdit(money.fmt(e.amount, e.currency).split(" ", 1)[1])
        self.amount.setFont(theme.mono_font())
        self.amount.setAlignment(Qt.AlignRight)
        self.account = QComboBox()
        with Session() as s:
            accs = accounts.list_accounts(s, self._entity(s, e.id))
        for a in accs:
            if (a.is_active and not (a.kind == "card" and a.closing_day and a.due_day)) or a.id == e.account_id:
                self.account.addItem(a.name, a.id)
        self.account.setCurrentIndex(max(0, self.account.findData(e.account_id)))
        self.note = QLineEdit(placeholderText="Opcional. Ex.: pago com 5 dias de atraso")
        self.difference = QLabel()
        self.difference.setProperty("role", "field")

        verb = {"expense": "pago", "income": "recebido"}.get(e.kind, "")
        form = QGridLayout()
        form.setHorizontalSpacing(theme.SP_M)
        form.setVerticalSpacing(3)
        rows = [(field_label("Data do pagamento" if not transfer else "Data", t), self.when)]
        if not transfer:
            rows += [(field_label(f"Valor {verb}", t, "Se pagou com juros, multa ou desconto, informe o valor\n"
                                                       "que de fato saiu (ou entrou). O previsto fica guardado\n"
                                                       "para o relatório de juros e descontos."), self.amount),
                     (field_label("Conta", t, "De onde saiu (ou onde entrou) o dinheiro."), self.account)]
        rows.append((field_label("Observação", t, "Vai para o fim das observações do lançamento."), self.note))
        for i, (lbl, w) in enumerate(rows):
            form.addWidget(lbl, 2 * i, 0)
            form.addWidget(w, 2 * i + 1, 0)

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancelar", "secondary")
        self.ok = button("Confirmar", "primary")
        btns.addWidget(cancel)
        btns.addWidget(self.ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(info)
        lay.addLayout(form)
        lay.addWidget(self.difference)
        lay.addWidget(self.error)
        lay.addLayout(btns)

        self.amount.textChanged.connect(self._update)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.confirm)
        self.amount.returnPressed.connect(self.confirm)
        self.note.returnPressed.connect(self.confirm)
        self._update()

    @staticmethod
    def _entity(s, entry_id: int) -> int:
        from finora.models import Entry
        return s.get(Entry, entry_id).entity_id

    def _value(self) -> Decimal | None:
        try:
            return money.parse(self.amount.text())
        except ValueError:
            return None

    def _update(self):
        """Mostra quanto saiu a mais (juros/multa) ou a menos (desconto) que o previsto."""
        v = self._value()
        diff = (v - self.entry.amount) if v is not None and self.entry.kind in entries.RESULT_KINDS else Decimal(0)
        cur = self.entry.currency
        if diff > 0:
            self.difference.setText(f"A mais que o previsto (juros/multa): {money.fmt(diff, cur)}")
        elif diff < 0:
            self.difference.setText(f"A menos que o previsto (desconto): {money.fmt(-diff, cur)}")
        self.difference.setVisible(diff != 0)

    def confirm(self):
        transfer = self.entry.kind in entries.NO_CATEGORY
        v = None if transfer else self._value()
        if not transfer and v is None:
            self.error.setText("Valor inválido. Use o formato 1.234,56.")
            self.error.show()
            return
        try:
            with Session() as s:
                entries.pay(s, self.entry.id, self.when.date().toPython(), amount=v,
                            account_id=None if transfer else self.account.currentData(), note=self.note.text())
        except ValueError as err:
            self.error.setText(str(err))
            self.error.show()
            return
        self.paid = True
        self.accept()
