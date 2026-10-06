"""Tela de Contas: cartões com saldo + formulário de nova conta/edição (mockup "Contas")."""
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QLineEdit, QComboBox, QCheckBox, QProgressBar, QScrollArea, QSizePolicy, QSpinBox,
    QGridLayout, QHBoxLayout, QVBoxLayout,
)

from finora.core import money
from finora.core.db import Session
from finora.services import accounts, cards
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.card_statements import open_statements
from finora.ui.widgets import button, field_label, icon_label, lock_icon, show_upgrade, upgrade_box

KIND_ICONS = {
    "bank": "fa6s.building-columns",
    "cash": "fa6s.wallet",
    "card": "fa6s.credit-card",
    "investment": "fa6s.piggy-bank",
}
CARD_MIN_W = 220
PANEL_W = 300
STACK_BELOW = 760   # abaixo dessa largura, o formulário ocupa o lugar dos cartões


def _repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)


class AccountCard(QFrame):
    edit = Signal(int)
    toggle = Signal(int, bool)
    statements = Signal(int)

    def __init__(self, a: accounts.AccountView, t: dict, selected: bool = False, card: dict | None = None):
        super().__init__(objectName="card")
        self.setProperty("inactive", not a.is_active)
        self.setProperty("selected", selected)
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

        info = QLabel(f"{a.kind_label} · {a.card_info}" if a.kind == "card" else a.kind_label)
        info.setProperty("role", "field")
        lay.addWidget(info)
        lay.addSpacing(theme.SP_S)

        bal = QLabel(money.fmt(a.balance, a.currency))
        big = theme.mono_font()
        big.setPointSize(13)
        bal.setFont(big)
        if a.kind == "card":
            bal.setToolTip("No cartão, o saldo negativo é o que você está devendo\n"
                           "(inclui parcelas das próximas faturas).")
        lay.addWidget(bal)
        if card:                       # cartão com fechamento/vencimento: fatura atual e limite
            st = card["statement"]
            fat = QLabel(f"Fatura {st.label}: {money.fmt(st.charges, a.currency)} · {st.status_label(card['today'])}")
            fat.setProperty("role", "field")
            lay.addWidget(fat)
            if card["free"] is not None and a.credit_limit:
                used = max(0, min(100, int((a.credit_limit - card["free"]) * 100 / a.credit_limit)))
                bar = QProgressBar(textVisible=False, maximum=100, value=used)
                bar.setFixedHeight(5)
                bar.setToolTip(f"{used}% do limite usado")
                lay.addWidget(bar)
                free = QLabel(f"Limite disponível {money.fmt(card['free'], a.currency)} "
                              f"de {money.fmt(a.credit_limit, a.currency)}")
                free.setProperty("role", "field")
                lay.addWidget(free)
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
        if card:
            fb = button("Faturas", "link", t, "fa6s.file-invoice-dollar")
            fb.setToolTip("Ver as faturas, as compras de cada uma e pagar")
            fb.clicked.connect(lambda: self.statements.emit(a.id))
            actions.addWidget(fb)
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
        self._cards: dict[int, dict] = {}   # cartões configurados: fatura atual e limite livre
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

        # Esquerda: cartões (rolam). Direita: formulário, como nas outras telas.
        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        self.empty_lbl = QLabel("Nenhuma conta para mostrar.")
        self.empty_lbl.setProperty("role", "muted")

        body = QWidget(objectName="pageBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(theme.SP_L)
        bl.addLayout(self.grid)
        bl.addWidget(self.empty_lbl)
        bl.addStretch(1)
        self.scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(body)

        self.left = QWidget()
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        ll.addLayout(bar)
        ll.addWidget(self.scroll, 1)

        self.panel = QWidget(objectName="pageBody")
        self.form_slot = QVBoxLayout(self.panel)
        self.form_slot.setContentsMargins(0, 0, 0, 0)
        self.form_slot.setSpacing(theme.SP_L)
        self.panel_scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        self.panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.panel_scroll.setWidget(self.panel)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addWidget(self.left, 1)
        root.addWidget(self.panel_scroll)

        self._open = False   # em tela estreita: o formulário está aberto no lugar dos cartões?
        self._build_form()
        self.show_inactive.toggled.connect(self.refresh)
        self.new_btn.clicked.connect(lambda: self._new(open_panel=True))
        self._new()

    # ---------- formulário ----------
    def _build_form(self):
        self.form = QFrame(objectName="card")
        fl = QVBoxLayout(self.form)
        fl.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        fl.setSpacing(theme.SP_M)
        self.form_title = QLabel(objectName="sectionTitle")
        fl.addWidget(self.form_title)

        g = QVBoxLayout()
        g.setSpacing(3)
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

        self.currency_lbl = field_label("Moeda", self.t)
        self.balance_lbl = field_label("Saldo inicial", self.t, "")
        for i, (lbl, w) in enumerate(((field_label("Nome", self.t), self.name_edit),
                                      (field_label("Tipo", self.t), self.kind_box),
                                      (self.currency_lbl, self.currency_box),
                                      (self.balance_lbl, self.balance_edit))):
            if i:
                g.addSpacing(theme.SP_S + 2)
            g.addWidget(lbl)
            g.addWidget(w)
        fl.addLayout(g)

        # Só para cartão: fechamento, vencimento e limite
        self.card_box = QWidget()
        cg = QGridLayout(self.card_box)
        cg.setContentsMargins(0, theme.SP_S, 0, 0)
        cg.setHorizontalSpacing(theme.SP_M)
        cg.setVerticalSpacing(3)
        self.closing_spin = QSpinBox(minimum=0, maximum=31, specialValueText="—")
        self.due_spin = QSpinBox(minimum=0, maximum=31, specialValueText="—")
        self.limit_edit = QLineEdit(placeholderText="Opcional")
        for w in (self.closing_spin, self.due_spin, self.limit_edit):
            w.setFont(theme.mono_font())
        self.limit_edit.setAlignment(Qt.AlignRight)
        cg.addWidget(field_label("Fecha dia", self.t, "Dia em que a fatura fecha. Compras feitas nesse dia\n"
                                                      "ou depois já vão para a fatura seguinte."), 0, 0)
        cg.addWidget(field_label("Vence dia", self.t, "Dia de pagar a fatura."), 0, 1)
        cg.addWidget(self.closing_spin, 1, 0)
        cg.addWidget(self.due_spin, 1, 1)
        cg.addWidget(field_label("Limite", self.t, "Limite total do cartão. Serve para mostrar quanto ainda\n"
                                                   "dá para gastar."), 2, 0, 1, 2)
        cg.addWidget(self.limit_edit, 3, 0, 1, 2)
        self.card_hint = QLabel("Informe o fechamento e o vencimento para as compras irem para a fatura certa.",
                                wordWrap=True)
        self.card_hint.setProperty("role", "field")
        cg.addWidget(self.card_hint, 4, 0, 1, 2)
        fl.addWidget(self.card_box)

        if not accounts.multi_currency():
            msg = "Contas em outra moeda fazem parte das edições Plus e Pro."
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
        self.cancel_btn.clicked.connect(self._cancel)
        for e in (self.name_edit, self.balance_edit):
            e.returnPressed.connect(self._save)
        self.balance_edit.textChanged.connect(lambda: self._mark_invalid(False))

        self.form_slot.addWidget(self.form)
        self.lock = upgrade_box(f"Na edição Free você pode ter até {accounts.limit()} contas ativas. "
                                "Inative uma conta ou faça upgrade para ter contas ilimitadas.", self.t, self,
                                compact=True)
        self.lock.hide()
        self.form_slot.addWidget(self.lock)
        self.form_slot.addStretch(1)

    def _kind_changed(self):
        self.card_box.setVisible(self.kind_box.currentData() == "card")
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

    # ---------- painel: lado a lado, ou no lugar dos cartões em tela estreita ----------
    def _narrow(self) -> bool:
        return self.width() < STACK_BELOW

    def _arrange(self):
        narrow = self._narrow()
        self.panel_scroll.setVisible(not narrow or self._open)
        self.left.setVisible(not (narrow and self._open))
        self.panel_scroll.setFixedWidth(max(PANEL_W, self.width() - 28) if narrow else PANEL_W)
        self.cancel_btn.setVisible(narrow or self.editing is not None)

    def _cancel(self):
        self._open = False
        was_editing = self.editing is not None
        self._new()
        if was_editing:
            self._layout_cards(force=True)   # tira o destaque do cartão

    def _new(self, open_panel: bool = False):
        self.editing = None
        self.form_title.setText("Nova conta")
        self.name_edit.clear()
        self.kind_box.setCurrentIndex(0)
        self._set_currency(self.profile.currency)
        self.balance_edit.setText("0,00")
        self.closing_spin.setValue(0)
        self.due_spin.setValue(0)
        self.limit_edit.clear()
        self._error(None)
        self._mark_invalid(False)
        self._update_lock()
        if open_panel:
            self._open = True
            self._layout_cards(force=True)
        self._arrange()
        if open_panel and self.form.isVisible():
            self.name_edit.setFocus()

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
        self.closing_spin.setValue(a.closing_day or 0)
        self.due_spin.setValue(a.due_day or 0)
        self.limit_edit.setText("" if a.credit_limit is None else
                                money.fmt(a.credit_limit, a.currency).split(" ", 1)[1])
        self._error(None)
        self._update_lock()
        self._open = True
        self._arrange()
        self._layout_cards(force=True)   # destaca o cartão em edição
        self.name_edit.setFocus()
        self.name_edit.selectAll()

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
        try:
            limit = money.parse(self.limit_edit.text()) if self.limit_edit.text().strip() else None
        except ValueError:
            self._error("Limite inválido. Use o formato 1.234,56.")
            return
        data = dict(name=self.name_edit.text(), kind=self.kind_box.currentData(), opening_balance=value,
                    currency=self.currency_box.currentData(), closing_day=self.closing_spin.value() or None,
                    due_day=self.due_spin.value() or None, credit_limit=limit)
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
        self._open = False
        self._new()
        self.refresh()

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
            self._open = False
            self._new()
        self.refresh()

    def refresh(self):
        today = date.today()
        with Session() as s:
            self._items = accounts.list_accounts(s, self.profile.id, self.show_inactive.isChecked())
            self._cards = {}
            for a in self._items:
                if a.kind == "card" and a.closing_day and a.due_day:
                    self._cards[a.id] = {"statement": cards.current(s, a.id, today), "today": today,
                                         "free": cards.available_limit(s, a.id)}
        n = len(accounts.money_accounts(self._items))
        has_card = any(a.kind == "card" and a.is_active for a in self._items)
        self.total_lbl.setText(f"Saldo em contas ({n} {'conta' if n == 1 else 'contas'}"
                               + (", sem cartões)" if has_card else ")"))
        self.total_val.setText(money.fmt(accounts.total_balance(self._items), self.profile.currency))
        self.total_lbl.setToolTip("Soma das contas ativas, sem os cartões de crédito.\n"
                                  "O que você deve no cartão aparece nas faturas (A pagar).")
        self._layout_cards(force=True)
        if self.editing is None:
            self._update_lock()
        self._arrange()

    def _layout_cards(self, force: bool = False):
        cols = max(1, (self.scroll.viewport().width() + 10) // (CARD_MIN_W + 10))
        if not force and cols == self._cols and self.grid.count() == len(self._items):
            return
        self._cols = cols
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.setParent(None)  # sai da tela já, não só quando o Qt destruir
                w.deleteLater()
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)
        editing_id = self.editing.id if self.editing else None
        for i, a in enumerate(self._items):
            card = AccountCard(a, self.t, selected=a.id == editing_id, card=self._cards.get(a.id))
            card.statements.connect(self._open_statements)
            card.edit.connect(self._edit)
            card.toggle.connect(self._toggle)
            self.grid.addWidget(card, i // cols, i % cols)
        self.empty_lbl.setVisible(not self._items)

    def _open_statements(self, account_id: int):
        a = next(x for x in self._items if x.id == account_id)
        if open_statements(self, account_id, a.currency, self.t):
            self.message.emit("Pagamento de fatura registrado.")
            self.refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._arrange()
        self._layout_cards()

    def apply_theme(self, t: dict):
        self.t = t  # ícones já existentes são redesenhados por widgets.retheme
