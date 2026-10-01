"""Tela de Contas: cartões com saldo + formulário de nova conta/edição (mockup "Contas")."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QLineEdit, QComboBox, QCheckBox, QScrollArea, QSizePolicy,
    QGridLayout, QHBoxLayout, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, field_label, icon_label, lock_icon, show_upgrade, upgrade_box

KIND_ICONS = {
    "bank": "fa6s.building-columns",
    "cash": "fa6s.wallet",
    "card": "fa6s.credit-card",
    "investment": "fa6s.piggy-bank",
}
CARD_MIN_W = 240


def _repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)


class AccountCard(QFrame):
    edit = Signal(int)
    toggle = Signal(int, bool)

    def __init__(self, a: accounts.AccountView, t: dict):
        super().__init__(objectName="card")
        self.setProperty("inactive", not a.is_active)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_L, 10, theme.SP_L, 10)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(theme.SP_M)
        icon = icon_label(KIND_ICONS.get(a.kind, "fa6s.wallet"), t, "acc" if a.is_active else "mut", 14)
        name = QLabel(a.name, objectName="cardTitle")
        name.setMinimumWidth(1)
        name.setToolTip(a.name)
        cur = QLabel(a.currency)
        cur.setProperty("role", "badge")
        cur.setFont(theme.mono_font())
        top.addWidget(icon)
        top.addWidget(name, 1)
        if not a.is_active:
            off = QLabel("Inativa")
            off.setProperty("role", "badge")
            top.addWidget(off)
        top.addWidget(cur)
        lay.addLayout(top)

        info = QLabel(a.kind_label)
        info.setProperty("role", "field")
        lay.addWidget(info)
        lay.addSpacing(theme.SP_S)

        bal = QLabel(money.fmt(a.balance, a.currency))
        big = theme.mono_font()
        big.setPointSize(13)
        bal.setFont(big)
        if a.kind == "card":
            bal.setToolTip("No cartão, o saldo negativo é o que você está devendo.")
        lay.addWidget(bal)
        lay.addSpacing(theme.SP_S)

        actions = QHBoxLayout()
        actions.setSpacing(theme.SP_L)
        ed = button("Editar", "link", t, "fa6s.pen")
        ed.clicked.connect(lambda: self.edit.emit(a.id))
        tg = button("Inativar" if a.is_active else "Ativar", "link", t,
                    "fa6s.box-archive" if a.is_active else "fa6s.rotate-left")
        tg.setToolTip("Inativar esconde a conta das listas, sem apagar nada." if a.is_active
                      else "Volta a mostrar a conta nas listas.")
        tg.clicked.connect(lambda: self.toggle.emit(a.id, not a.is_active))
        actions.addWidget(ed)
        actions.addWidget(tg)
        actions.addStretch(1)
        lay.addLayout(actions)


class AccountsPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile = profile
        self.t = t
        self.editing: accounts.AccountView | None = None
        self._items: list[accounts.AccountView] = []
        self._cols = 0

        # Barra superior
        self.total_lbl = QLabel()
        self.total_val = QLabel()
        self.total_val.setProperty("role", "total")
        self.total_val.setFont(theme.mono_font())
        self.show_inactive = QCheckBox("Mostrar inativas")
        self.new_btn = button("Nova conta", "secondary", t, "fa6s.plus", "fg")
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        bar.addWidget(self.total_lbl)
        bar.addWidget(self.total_val)
        bar.addStretch(1)
        bar.addWidget(self.show_inactive)
        bar.addWidget(self.new_btn)

        # Grade de cartões + formulário, tudo rolando junto
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        self.empty_lbl = QLabel("Nenhuma conta para mostrar.")
        self.empty_lbl.setProperty("role", "muted")
        self.form_slot = QVBoxLayout()

        body = QWidget(objectName="pageBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(theme.SP_L)
        bl.addLayout(self.grid)
        bl.addWidget(self.empty_lbl)
        bl.addLayout(self.form_slot)
        bl.addStretch(1)
        self.scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        self.scroll.setWidget(body)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(10)
        root.addLayout(bar)
        root.addWidget(self.scroll, 1)

        self._build_form()
        self.show_inactive.toggled.connect(self.refresh)
        self.new_btn.clicked.connect(self._new)

    # ---------- formulário ----------
    def _build_form(self):
        self.form = QFrame(objectName="card")
        self.form.setMaximumWidth(560)
        fl = QVBoxLayout(self.form)
        fl.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        fl.setSpacing(theme.SP_M)
        self.form_title = QLabel(objectName="sectionTitle")
        fl.addWidget(self.form_title)

        g = QGridLayout()
        g.setHorizontalSpacing(theme.SP_M)
        g.setVerticalSpacing(3)
        self.name_edit = QLineEdit(maxLength=80, placeholderText="Ex.: Nubank, Carteira")
        self.kind_box = QComboBox()
        for code, label in accounts.KINDS.items():
            self.kind_box.addItem(label, code)
        self.currency_box = QComboBox()
        for code, (sym, label) in money.CURRENCIES.items():
            self.currency_box.addItem(f"{code} — {label}", code)
        self.balance_edit = QLineEdit()
        self.balance_edit.setFont(theme.mono_font())
        self.balance_edit.setAlignment(Qt.AlignRight)

        g.addWidget(field_label("Nome", self.t), 0, 0)
        g.addWidget(self.name_edit, 1, 0)
        g.addWidget(field_label("Tipo", self.t), 0, 1)
        g.addWidget(self.kind_box, 1, 1)
        self.currency_lbl = field_label("Moeda", self.t)
        g.addWidget(self.currency_lbl, 2, 0)
        g.addWidget(self.currency_box, 3, 0)
        self.balance_lbl = field_label("Saldo inicial", self.t, "")
        g.addWidget(self.balance_lbl, 2, 1)
        g.addWidget(self.balance_edit, 3, 1)
        g.setRowMinimumHeight(2, 20)
        fl.addLayout(g)

        if not accounts.multi_currency():
            msg = "Contas em outra moeda fazem parte da edição Pro."
            self.currency_lbl.layout().insertWidget(1, lock_icon(msg, self.t))
            self.currency_box.setEnabled(False)
            self.currency_box.setToolTip(msg)

        self.form_error = QLabel(wordWrap=True)
        self.form_error.setProperty("role", "error")
        self.form_error.hide()
        fl.addWidget(self.form_error)

        btns = QHBoxLayout()
        self.save_btn = button("Salvar", "primary")
        self.cancel_btn = button("Cancelar", "secondary")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        btns.addStretch(1)
        fl.addLayout(btns)

        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self._new)
        for e in (self.name_edit, self.balance_edit):
            e.returnPressed.connect(self._save)
        self.balance_edit.textChanged.connect(lambda: self._mark_invalid(False))

        self.form_slot.addWidget(self.form, 0, Qt.AlignLeft)
        self.lock = upgrade_box(f"Na edição Free você pode ter até {accounts.limit()} contas ativas. "
                                "Inative uma conta ou faça upgrade para ter contas ilimitadas.", self.t, self)
        self.lock.setMaximumWidth(560)
        self.lock.hide()
        self.form_slot.addWidget(self.lock, 0, Qt.AlignLeft)

    def _kind_changed(self):
        if self.kind_box.currentData() == "card":
            self.balance_lbl.label.setText("Fatura inicial")
            tip = ("Quanto você devia no cartão quando começou a usar o Finora.\n"
                   "Digite sem sinal: o saldo do cartão fica negativo.")
        else:
            self.balance_lbl.label.setText("Saldo inicial")
            tip = ("Quanto tinha nessa conta quando você começou a usar o Finora.\n"
                   "Se estava no negativo, use o sinal de menos.")
        self.balance_lbl.help.setToolTip(tip)

    def _mark_invalid(self, invalid: bool):
        self.balance_edit.setProperty("invalid", invalid)
        _repolish(self.balance_edit)

    def _error(self, msg: str | None):
        self.form_error.setText(msg or "")
        self.form_error.setVisible(bool(msg))

    def _set_currency(self, code: str):
        self.currency_box.setCurrentIndex(max(0, self.currency_box.findData(code)))

    def _new(self):
        self.editing = None
        self.form_title.setText("Nova conta")
        self.name_edit.clear()
        self.kind_box.setCurrentIndex(0)
        self._set_currency(self.profile.currency)
        self.balance_edit.setText("0,00")
        self.cancel_btn.hide()
        self._error(None)
        self._mark_invalid(False)
        self._update_lock()
        if self.form.isVisible():
            self.name_edit.setFocus()
            self.scroll.ensureWidgetVisible(self.form)

    def _edit(self, account_id: int):
        a = next((x for x in self._items if x.id == account_id), None)
        if a is None:
            return
        self.editing = a
        self.form_title.setText(f"Editar conta · {a.name}")
        self.name_edit.setText(a.name)
        self.kind_box.setCurrentIndex(self.kind_box.findData(a.kind))
        self._set_currency(a.currency)
        ob = abs(a.opening_balance) if a.kind == "card" else a.opening_balance
        self.balance_edit.setText(money.fmt(ob, a.currency).replace(money.symbol(a.currency) + " ", ""))
        self.cancel_btn.show()
        self._error(None)
        self._update_lock()
        self.name_edit.setFocus()
        self.name_edit.selectAll()
        self.scroll.ensureWidgetVisible(self.form)

    def _update_lock(self):
        """Na Free, com o limite atingido, o formulário de nova conta vira um convite para upgrade."""
        with Session() as s:
            blocked = self.editing is None and not accounts.can_add(s, self.profile.id)
        self.lock.setVisible(blocked)
        self.form.setVisible(not blocked)

    def _save(self):
        try:
            value = money.parse(self.balance_edit.text())
        except ValueError:
            self._mark_invalid(True)
            self._error("Valor inválido. Use o formato 1.234,56.")
            return
        data = dict(name=self.name_edit.text(), kind=self.kind_box.currentData(), opening_balance=value,
                    currency=self.currency_box.currentData())
        try:
            with Session() as s:
                if self.editing:
                    accounts.update(s, self.editing.id, **data)
                    msg = f"Conta \"{data['name'].strip()}\" atualizada."
                else:
                    accounts.create(s, self.profile.id, **data)
                    msg = f"Conta \"{data['name'].strip()}\" criada."
        except accounts.LimitError as e:
            show_upgrade(self, str(e))
            return
        except ValueError as e:
            self._error(str(e))
            return
        self.message.emit(msg)
        self.refresh()
        self._new()

    # ---------- lista ----------
    def _toggle(self, account_id: int, active: bool):
        a = next(x for x in self._items if x.id == account_id)
        try:
            with Session() as s:
                accounts.set_active(s, account_id, active)
        except accounts.LimitError as e:
            show_upgrade(self, str(e))
            return
        if active:
            self.message.emit(f"Conta \"{a.name}\" ativada.")
        else:
            hint = "" if self.show_inactive.isChecked() else " Para vê-la, marque \"Mostrar inativas\"."
            self.message.emit(f"Conta \"{a.name}\" inativada.{hint}")
        if self.editing and self.editing.id == account_id:
            self._new()
        self.refresh()

    def refresh(self):
        with Session() as s:
            self._items = accounts.list_accounts(s, self.profile.id, self.show_inactive.isChecked())
        active = [a for a in self._items if a.is_active]
        self.total_lbl.setText(f"Saldo total ({len(active)} {'conta' if len(active) == 1 else 'contas'})")
        self.total_val.setText(money.fmt(accounts.total_balance(self._items), self.profile.currency))
        self.total_lbl.setToolTip("Soma dos saldos das contas ativas. Cartões entram negativos (o que você deve).")
        self._cols = 0
        self._layout_cards()
        if self.editing is None:
            self._update_lock()

    def _layout_cards(self):
        cols = max(1, (self.scroll.viewport().width() + 10) // (CARD_MIN_W + 10))
        if cols == self._cols and self.grid.count() == len(self._items):
            return
        self._cols = cols
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.setParent(None)  # sai da tela já, não só quando o Qt destruir
                w.deleteLater()
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)
        for i, a in enumerate(self._items):
            card = AccountCard(a, self.t)
            card.edit.connect(self._edit)
            card.toggle.connect(self._toggle)
            self.grid.addWidget(card, i // cols, i % cols)
        self.empty_lbl.setVisible(not self._items)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_cards()

    def apply_theme(self, t: dict):
        self.t = t  # ícones já existentes são redesenhados por widgets.retheme
