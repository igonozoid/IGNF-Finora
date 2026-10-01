"""Assistente de primeiro uso: nome e moeda, 1ª conta, categorias padrão."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QWidget, QFrame, QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QHBoxLayout, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import setup
from finora.ui import theme
from finora.ui.widgets import field_label

ACCOUNT_DEFAULT_NAMES = {
    "bank": "Conta corrente",
    "cash": "Carteira",
    "card": "Cartão de crédito",
    "investment": "Reserva",
}


class FirstRunWizard(QDialog):
    def __init__(self, t: dict, parent=None):
        super().__init__(parent)
        self.t = t
        self.profile = None
        self.setObjectName("wizard")
        self.setWindowTitle("IGNF Finora — Primeiro uso")
        self.resize(560, 480)
        self.setMinimumSize(480, 420)

        self.pages = QStackedWidget()
        for build in (self._page_you, self._page_account, self._page_categories):
            self.pages.addWidget(build())

        # Indicador de passos
        self.steps = []
        steps_row = QHBoxLayout()
        steps_row.setSpacing(theme.SP_S)
        for _ in range(self.pages.count()):
            seg = QFrame()
            seg.setFixedHeight(3)
            self.steps.append(seg)
            steps_row.addWidget(seg)
        self.step_lbl = QLabel(objectName="wizardStep")

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()

        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, theme.SP_L)
        body.setSpacing(theme.SP_M)
        body.addLayout(steps_row)
        body.addWidget(self.step_lbl)
        body.addWidget(self.pages, 1)
        body.addWidget(self.error)

        footer = QFrame(objectName="wizardFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, theme.SP_M + 2, 24, theme.SP_M + 2)
        self.back_btn = QPushButton("Voltar")
        self.back_btn.setProperty("variant", "secondary")
        self.back_btn.setAutoDefault(False)
        self.next_btn = QPushButton()
        self.next_btn.setProperty("variant", "primary")
        self.next_btn.setDefault(True)
        fl.addStretch(1)
        fl.addWidget(self.back_btn)
        fl.addWidget(self.next_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(body, 1)
        root.addWidget(footer)

        self.back_btn.clicked.connect(lambda: self._go(self.pages.currentIndex() - 1))
        self.next_btn.clicked.connect(self._next)
        self._go(0)

    # ---------- páginas ----------
    def _page(self, title: str, text: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, theme.SP_S, 0, 0)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(QLabel(title, objectName="wizardTitle"))
        sub = QLabel(text, wordWrap=True)
        sub.setProperty("role", "muted")
        lay.addWidget(sub)
        lay.addSpacing(theme.SP_S)
        return w, lay

    def _field(self, lay, label, widget, help_text=None):
        box = QVBoxLayout()
        box.setSpacing(3)
        lbl = field_label(label, self.t, help_text)
        box.addWidget(lbl)
        box.addWidget(widget)
        lay.addLayout(box)
        return lbl

    def _page_you(self):
        w, lay = self._page("Boas-vindas ao IGNF Finora!",
                            "Vamos deixar tudo pronto em 3 passos rápidos. Você pode mudar tudo isso depois.")
        self.name_edit = QLineEdit(placeholderText="Ex.: Marina", maxLength=120)
        self._field(lay, "Como podemos te chamar?", self.name_edit)
        self.currency_box = QComboBox()
        for code, (sym, label) in money.CURRENCIES.items():
            self.currency_box.addItem(f"{label} ({sym})", code)
        self._field(lay, "Moeda principal", self.currency_box,
                    "A moeda em que você recebe e gasta no dia a dia.\nOs relatórios e o saldo total usam essa moeda.")
        self.currency_box.currentIndexChanged.connect(self._update_symbol)
        lay.addStretch(1)
        return w

    def _page_account(self):
        w, lay = self._page("Sua primeira conta",
                            "Onde está seu dinheiro hoje? Comece por uma conta — dá para cadastrar outras depois.")
        self.kind_box = QComboBox()
        for code, label in setup.ACCOUNT_KINDS.items():
            self.kind_box.addItem(label, code)
        self._field(lay, "Tipo", self.kind_box)
        self.acc_name_edit = QLineEdit(ACCOUNT_DEFAULT_NAMES["bank"], maxLength=80)
        self._field(lay, "Nome da conta", self.acc_name_edit,
                    "Um nome fácil de reconhecer, como o nome do banco (\"Nubank\", \"Itaú\").")

        row = QHBoxLayout()
        row.setSpacing(theme.SP_S)
        self.symbol_lbl = QLabel()
        self.symbol_lbl.setFont(theme.mono_font())
        self.symbol_lbl.setProperty("role", "muted")
        self.balance_edit = QLineEdit("0,00")
        self.balance_edit.setFont(theme.mono_font())
        self.balance_edit.setAlignment(Qt.AlignRight)
        self.balance_edit.setMaximumWidth(160)
        row.addWidget(self.symbol_lbl)
        row.addWidget(self.balance_edit)
        row.addStretch(1)
        box = QVBoxLayout()
        box.setSpacing(3)
        self.balance_lbl = field_label("Saldo atual", self.t, "")
        box.addWidget(self.balance_lbl)
        box.addLayout(row)
        lay.addLayout(box)

        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        self.acc_name_edit.textEdited.connect(lambda: setattr(self, "_acc_name_touched", True))
        self.balance_edit.textChanged.connect(lambda: self._mark_invalid(self.balance_edit, False))
        self._acc_name_touched = False
        self._kind_changed()
        self._update_symbol()
        lay.addStretch(1)
        return w

    def _page_categories(self):
        w, lay = self._page("Categorias",
                            "Categorias são grupos que mostram para onde vai o seu dinheiro. "
                            "Preparamos uma lista que já monta a sua DRE pessoal — o resumo mensal "
                            "de quanto entrou, saiu e sobrou.")
        self.cat_check = QCheckBox("Criar as categorias prontas (recomendado)", checked=True)
        lay.addWidget(self.cat_check)
        self.cat_tree = QTreeWidget(headerHidden=True, rootIsDecorated=True)
        self.cat_tree.setFocusPolicy(Qt.NoFocus)
        bold = QFont()
        bold.setBold(True)
        for _group, _kind, name, children in setup.DEFAULT_CATEGORIES:
            item = QTreeWidgetItem([name])
            item.setFont(0, bold)
            item.addChildren([QTreeWidgetItem([c]) for c in children])
            self.cat_tree.addTopLevelItem(item)
        self.cat_tree.expandToDepth(0)
        lay.addWidget(self.cat_tree, 1)
        self.cat_check.toggled.connect(self.cat_tree.setEnabled)
        return w

    # ---------- comportamento ----------
    def _kind_changed(self):
        kind = self.kind_box.currentData()
        if not self._acc_name_touched:
            self.acc_name_edit.setText(ACCOUNT_DEFAULT_NAMES[kind])
        if kind == "card":
            self.balance_lbl.label.setText("Fatura em aberto")
            tip = "Quanto você já gastou no cartão e ainda não pagou.\nDigite o valor sem sinal."
        else:
            self.balance_lbl.label.setText("Saldo atual")
            tip = "Quanto tem nessa conta hoje.\nSe estiver no negativo (cheque especial), use o sinal de menos."
        self.balance_lbl.help.setToolTip(tip)

    def _update_symbol(self):
        if hasattr(self, "symbol_lbl"):
            self.symbol_lbl.setText(money.symbol(self.currency_box.currentData()))

    def _mark_invalid(self, edit: QLineEdit, invalid: bool):
        edit.setProperty("invalid", invalid)
        edit.style().unpolish(edit)
        edit.style().polish(edit)

    def _show_error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def _go(self, index: int):
        self._show_error(None)
        self.pages.setCurrentIndex(index)
        n = self.pages.count()
        for i, seg in enumerate(self.steps):
            seg.setProperty("step", "on" if i <= index else "off")
            seg.style().unpolish(seg)
            seg.style().polish(seg)
        self.step_lbl.setText(f"Passo {index + 1} de {n}")
        self.back_btn.setVisible(index > 0)
        self.next_btn.setText("Concluir" if index == n - 1 else "Próximo")
        focus = {0: self.name_edit, 1: self.acc_name_edit}.get(index)
        if focus:
            focus.setFocus()

    def _validate(self, index: int) -> bool:
        if index == 0 and not self.name_edit.text().strip():
            self._show_error("Digite seu nome (ou apelido) para continuar.")
            self.name_edit.setFocus()
            return False
        if index == 1:
            if not self.acc_name_edit.text().strip():
                self._show_error("Dê um nome para a conta.")
                self.acc_name_edit.setFocus()
                return False
            try:
                money.parse(self.balance_edit.text())
            except ValueError:
                self._mark_invalid(self.balance_edit, True)
                self._show_error("Valor inválido. Use o formato 1.234,56.")
                self.balance_edit.setFocus()
                return False
        return True

    def _next(self):
        i = self.pages.currentIndex()
        if not self._validate(i):
            return
        if i < self.pages.count() - 1:
            self._go(i + 1)
            return
        try:
            with Session() as s:
                self.profile = setup.run_first_setup(
                    s,
                    name=self.name_edit.text(),
                    currency=self.currency_box.currentData(),
                    account_name=self.acc_name_edit.text(),
                    account_kind=self.kind_box.currentData(),
                    balance=money.parse(self.balance_edit.text()),
                    default_categories=self.cat_check.isChecked(),
                )
        except ValueError as e:
            self._show_error(str(e))
            return
        self.accept()
