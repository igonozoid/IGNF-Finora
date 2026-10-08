"""Tela de Lançamentos: tabela filtrável por mês + formulário lateral (mockup "Lançamentos")."""
import calendar
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStyle, QStyledItemDelegate,
    QTableView, QVBoxLayout, QWidget,
)
import qtawesome as qta

from finora.core import money
from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.services import (
    accounts, attachments, budgets, cards, categories, contacts, cost_centers, entries, export, period_lock,
)
from finora.services.entries import EntryData, EntryView
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.attachments_box import AttachmentsBox
from finora.ui.card_statements import open_statements
from finora.ui.receipt_dialog import ReceiptDialog
from finora.ui.widgets import button, field_label, help_icon, lock_icon, show_upgrade, themed_icon

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
          "outubro", "novembro", "dezembro"]
COLS = ["", "VENC.", "DESCRIÇÃO", "CONTATO", "CATEGORIA", "CONTA", "VALOR", "SITUAÇÃO"]
C_KIND, C_DUE, C_DESC, C_CONTACT, C_CAT, C_ACC, C_VALUE, C_STATUS = range(len(COLS))
# Colunas que somem, nesta ordem, quando a tabela fica estreita: (coluna, largura mínima da tabela)
HIDE_WHEN_NARROW = [(C_CONTACT, 860), (C_ACC, 700), (C_CAT, 560)]
FORM_W = 320
STACK_BELOW = 760  # abaixo dessa largura da tela, o formulário ocupa o lugar da tabela


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)


# ---------- tabela ----------
EXPORT_LOCK = "Exportar para Excel e PDF é um recurso da edição Plus."


class EntriesModel(QAbstractTableModel):
    def __init__(self, t: dict):
        super().__init__()
        self.rows: list[EntryView] = []
        self.currency = "BRL"
        self.today = date.today()
        self.show_year = False
        self.attached: dict[int, int] = {}       # lançamento -> nº de comprovantes
        self.sort_col, self.sort_order = C_DUE, Qt.AscendingOrder
        self.set_theme(t)

    def set_theme(self, t: dict):
        self.t = t
        self.icons = {
            "income": qta.icon("fa6s.arrow-down", color=t["pos"]),
            "expense": qta.icon("fa6s.arrow-up", color=t["neg"]),
            "transfer": qta.icon("fa6s.right-left", color=t["mut"]),
            "repeat": qta.icon("fa6s.repeat", color=t["mut"]),
            "attach": qta.icon("fa6s.paperclip", color=t["mut"]),
        }
        self.layoutChanged.emit()

    def set_rows(self, rows: list[EntryView], show_year: bool):
        self.beginResetModel()
        self.rows, self.show_year, self.today = rows, show_year, date.today()
        self._apply_sort()
        self.endResetModel()

    def _key(self, e: EntryView):
        col = self.sort_col
        if col == C_DESC:
            return (e.description.lower(), e.due_date)
        if col == C_CONTACT:
            return ((e.contact or "").lower(), e.due_date)
        if col == C_CAT:
            return ((e.category or "").lower(), e.due_date)
        if col == C_ACC:
            return (e.account.lower(), e.due_date)
        if col == C_VALUE:
            return (-e.amount if e.kind == "expense" else e.amount, e.due_date)
        if col == C_STATUS:
            return (e.status_label(self.today), e.due_date)
        if col == C_KIND:
            return (e.kind, e.due_date)
        return (e.due_date, e.id)

    def _apply_sort(self):
        self.rows.sort(key=self._key, reverse=self.sort_order == Qt.DescendingOrder)

    def sort(self, column, order=Qt.AscendingOrder):
        """Clique no cabeçalho ordena pela coluna (de novo inverte)."""
        self.layoutAboutToBeChanged.emit()
        self.sort_col, self.sort_order = column, order
        self._apply_sort()
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return COLS[section]
            if role == Qt.TextAlignmentRole and section in (C_VALUE, C_STATUS):
                return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        e = self.rows[index.row()]
        col = index.column()
        if role == Qt.UserRole:
            return e
        if role == Qt.DisplayRole:
            if col == C_DUE:
                return e.due_date.strftime("%d/%m/%y" if self.show_year else "%d/%m")
            if col == C_DESC:
                return e.description + (f"  ({e.installment})" if e.installment else "")
            if col == C_CONTACT:
                return e.contact or ""
            if col == C_CAT:
                return "Transferência" if e.kind == "transfer" else (e.category or "Sem categoria")
            if col == C_ACC:
                return f"{e.account} → {e.dest_account}" if e.kind == "transfer" else e.account
            if col == C_VALUE:
                return money.fmt(-e.amount if e.kind == "expense" else e.amount, e.currency or self.currency)
            if col == C_STATUS:
                return e.status_label(self.today)
        if role == Qt.DecorationRole:
            if col == C_KIND:
                return self.icons[e.kind]
            if col == C_DESC and self.attached.get(e.id):
                return self.icons["attach"]
            if col == C_DESC and e.is_recurring:
                return self.icons["repeat"]
        if role == Qt.ForegroundRole:
            if col == C_VALUE and e.kind == "income":
                return QColor(self.t["pos"])
            if col in (C_CONTACT, C_ACC) or (col == C_VALUE and e.kind == "transfer") \
                    or (col == C_CAT and not e.category):
                return QColor(self.t["mut"])
            if col == C_DUE and e.is_late(self.today):
                return QColor(self.t["neg"])
        if role == Qt.FontRole and col in (C_DUE, C_VALUE):
            return theme.mono_font()
        if role == Qt.TextAlignmentRole:
            if col in (C_VALUE, C_STATUS):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if col == C_KIND:
                return int(Qt.AlignCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            if col == C_KIND:
                return entries.KINDS[e.kind]
            if col == C_DESC:
                tip = e.description
                if e.is_recurring:
                    tip += "\nLançamento que se repete"
                if e.installment:
                    tip += f"\nParcela {e.installment}"
                if e.document_no:
                    tip += f"\nDocumento: {e.document_no}"
                if n := self.attached.get(e.id):
                    tip += f"\n{n} comprovante{'s' if n > 1 else ''} anexado{'s' if n > 1 else ''}"
                return tip
            if col == C_STATUS and e.is_paid and e.paid_date:
                return f"{e.status_label(self.today)} em {e.paid_date.strftime('%d/%m/%Y')}"
        return None


class StatusDelegate(QStyledItemDelegate):
    """Situação como selo com borda (mockup); atrasado em vermelho, pago em verde."""

    def __init__(self, model: EntriesModel):
        super().__init__()
        self.model = model

    def paint(self, painter, option, index):
        opt = option
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        e: EntryView = index.data(Qt.UserRole)
        t = self.model.t
        text = e.status_label(self.model.today)
        color = t["neg"] if e.is_late(self.model.today) else t["pos"] if e.is_paid else t["fg"]
        f = option.font
        f.setBold(e.is_late(self.model.today))
        f.setPointSizeF(theme.FONT_PT - 1)
        painter.save()
        painter.setFont(f)
        fm = painter.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 14, fm.height() + 2
        r = QRectF(option.rect.right() - w - 8, option.rect.center().y() - h / 2, w, h)
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QPen(QColor(t["mut" if selected else "line"]), 1))
        painter.drawRoundedRect(r, 3, 3)
        painter.setPen(QColor(color))
        painter.drawText(r, Qt.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width() + 24, s.height())


# ---------- diálogos ----------
def ask_scope(parent, action: str, following: int) -> str | None:
    """Para séries: 'one', 'following' ou None (cancelou)."""
    box = QMessageBox(parent)
    box.setWindowTitle(f"{action} lançamento")
    box.setText(f"Este lançamento faz parte de uma série com mais {following} "
                f"{'lançamento' if following == 1 else 'lançamentos'} em aberto depois dele.")
    box.setInformativeText(f"{action} só este, ou este e os próximos?")
    one = box.addButton("Só este", QMessageBox.AcceptRole)
    nxt = box.addButton("Este e os próximos", QMessageBox.AcceptRole)
    box.addButton("Cancelar", QMessageBox.RejectRole)
    box.exec()
    return "one" if box.clickedButton() is one else "following" if box.clickedButton() is nxt else None


def confirm_delete(parent, e: EntryView) -> str | None:
    """Pergunta e exclui. Retorna a mensagem para a barra de status, ou None se cancelou."""
    with Session() as s:
        following = entries.in_series(s, e.id)
    if following:
        scope = ask_scope(parent, "Excluir", following)
        if scope is None:
            return None
    else:
        ok = QMessageBox.question(parent, "Excluir lançamento", f"Excluir \"{e.description}\"?\n"
                                  "Essa ação não pode ser desfeita.",
                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok != QMessageBox.Yes:
            return None
        scope = "one"
    with Session() as s:
        n = entries.delete(s, e.id, scope)
    return f"{n} lançamentos excluídos." if n > 1 else "Lançamento excluído."


# ---------- formulário ----------
class EntryForm(QFrame):
    saved = Signal(str, int)   # mensagem, id para selecionar
    closed = Signal()
    receipt_requested = Signal(object)   # EntryView

    def __init__(self, profile: Profile, t: dict):
        super().__init__(objectName="card")
        self.profile = profile
        self.t = t
        self.editing: EntryView | None = None
        self._last_account: int | None = None  # novo lançamento já vem com a última conta usada
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        lay.setSpacing(theme.SP_M)

        self.title = QLabel(objectName="sectionTitle")
        self.series_info = QLabel(wordWrap=True)
        self.series_info.setProperty("role", "muted")
        lay.addWidget(self.title)
        lay.addWidget(self.series_info)

        # Tipo
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.kind_group = QButtonGroup(self, exclusive=True)
        for i, (k, label) in enumerate(entries.KINDS.items()):
            b = QPushButton(label, checkable=True)
            b.setProperty("variant", "seg")
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(entries.KINDS) - 1 else "mid")
            b.setProperty("kind", k)
            b.setCursor(Qt.PointingHandCursor)
            self.kind_group.addButton(b, i)
            seg.addWidget(b, 1)
        lay.addLayout(seg)

        self.desc = QLineEdit(maxLength=200, placeholderText="Ex.: Conta de luz")
        lay.addLayout(self._field("Descrição", self.desc))

        row = QHBoxLayout()
        row.setSpacing(theme.SP_M)
        self.amount = QLineEdit(placeholderText="0,00")
        self.amount.setFont(theme.mono_font())
        self.amount.setAlignment(Qt.AlignRight)
        self.amount_lbl = field_label("Valor", t)
        self.due = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.due.setFont(theme.mono_font())
        row.addLayout(self._field(None, self.amount, self.amount_lbl), 1)
        self.due_lbl = field_label("Vencimento", t, "Data em que a conta vence ou o dinheiro deve entrar.")
        row.addLayout(self._field(None, self.due, self.due_lbl), 1)
        lay.addLayout(row)

        self.account = QComboBox()
        self.account_lbl = field_label("Conta", t)
        lay.addLayout(self._field(None, self.account, self.account_lbl))
        self.dest = QComboBox()
        self.dest_box = self._field("Para a conta", self.dest)
        lay.addLayout(self.dest_box)
        self.dest_amount = QLineEdit(placeholderText="0,00")
        self.dest_amount.setFont(theme.mono_font())
        self.dest_amount.setAlignment(Qt.AlignRight)
        self.dest_amount_lbl = field_label("Valor que chega", t, "As contas têm moedas diferentes: quanto entrou na\n"
                                                                 "conta de destino, já com o câmbio e as tarifas.")
        self.dest_amount_box = self._field(None, self.dest_amount, self.dest_amount_lbl)
        lay.addLayout(self.dest_amount_box)

        self.category = QComboBox()
        self.category_box = self._field("Categoria", self.category,
                                        help_text="Grupo do gasto ou do ganho. É o que monta a sua DRE pessoal.")
        lay.addLayout(self.category_box)
        self.cost_center = QComboBox()
        self.cc_box = self._field("Centro de custo", self.cost_center,
                                  help_text="Outro jeito de agrupar além da categoria: Casa, Carro, Viagem…\n"
                                            "Cadastre em Centros de custo (opcional).")
        lay.addLayout(self.cc_box)
        self._has_cc = False
        self.contact = QComboBox(editable=True)
        self.contact.lineEdit().setPlaceholderText("Opcional")
        self.contact.setInsertPolicy(QComboBox.NoInsert)
        self.contact_box = self._field("Contato", self.contact,
                                       help_text="Quem você paga ou quem te paga (opcional).\n"
                                                 "Digite um nome novo para cadastrar.")
        lay.addLayout(self.contact_box)
        self.doc = QLineEdit(maxLength=40, placeholderText="Opcional")
        self.doc_box = self._field("Nº do documento", self.doc,
                                   help_text="Número do boleto, da nota fiscal ou do recibo, se tiver.")
        lay.addLayout(self.doc_box)

        prow = QHBoxLayout()
        prow.setSpacing(theme.SP_M)
        self.paid = QCheckBox()
        self.paid_date = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.paid_date.setFont(theme.mono_font())
        prow.addWidget(self.paid)
        prow.addStretch(1)
        prow.addWidget(self.paid_date)
        self.paid_row = QWidget()
        self.paid_row.setLayout(prow)
        prow.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.paid_row)
        self.card_info = QLabel(wordWrap=True)       # "Vai para a fatura nov/2026 (vence 05/11)"
        self.card_info.setProperty("role", "field")
        self.card_info.hide()
        lay.addWidget(self.card_info)

        # Repetição (só na criação)
        self.repeat_frame = QWidget()
        rl = QVBoxLayout(self.repeat_frame)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(3)
        rrow = QHBoxLayout()
        rrow.setSpacing(theme.SP_M)
        self.repeat = QComboBox()
        for k, (label, *_r) in entries.REPEATS.items():
            self.repeat.addItem(label, k)
        self.times = QSpinBox(minimum=2, maximum=entries.MAX_REPEAT, value=12, suffix=" vezes")
        self.times.setFont(theme.mono_font())
        rrow.addWidget(self.repeat, 1)
        rrow.addWidget(self.times)
        rl.addWidget(field_label("Repetição", t, "Parcelado: divide o valor total em parcelas mensais.\n"
                                                 "Todo mês/semana/ano: repete o mesmo valor várias vezes."))
        rl.addLayout(rrow)
        self.repeat_preview = QLabel(wordWrap=True)
        self.repeat_preview.setProperty("role", "field")
        rl.addWidget(self.repeat_preview)
        lay.addWidget(self.repeat_frame)
        self.attach = AttachmentsBox(t)
        lay.addWidget(self.attach)

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)

        btns = QHBoxLayout()
        self.save_btn = button("Salvar", "primary")
        self.cancel_btn = button("Cancelar", "secondary")
        self.delete_btn = button("Excluir", "danger")
        self.receipt_btn = button("Recibo", "secondary", t, "fa6s.receipt", "fg")
        self.receipt_btn.setToolTip("Imprimir ou salvar o recibo deste lançamento (1 ou 2 vias)")
        self.receipt_btn.clicked.connect(lambda: self.editing and self.receipt_requested.emit(self.editing))
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.receipt_btn)
        btns.addStretch(1)
        btns.addWidget(self.delete_btn)
        lay.addLayout(btns)
        lay.addStretch(1)

        self.kind_group.idToggled.connect(lambda _i, on: on and self._kind_changed())
        self.repeat.currentIndexChanged.connect(self._update_repeat)
        self.times.valueChanged.connect(self._update_repeat)
        self.amount.textChanged.connect(self._update_repeat)
        self.due.dateChanged.connect(self._update_repeat)
        self.due.dateChanged.connect(self._card_mode)
        self.account.currentIndexChanged.connect(self._card_mode)
        self.account.currentIndexChanged.connect(self._currency_mode)
        self.dest.currentIndexChanged.connect(self._currency_mode)
        self.paid.toggled.connect(self.paid_date.setEnabled)
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self.closed.emit)
        self.delete_btn.clicked.connect(self._delete)
        for e in (self.desc, self.amount, self.doc):
            e.returnPressed.connect(self._save)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.closed.emit,
                  context=Qt.WidgetWithChildrenShortcut)

    def _field(self, label, widget, label_widget=None, help_text=None) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(3)
        box.addWidget(label_widget or field_label(label, self.t, help_text))
        box.addWidget(widget)
        return box

    @staticmethod
    def _set_visible(layout, visible: bool):
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w:
                w.setVisible(visible)

    # ----- dados -----
    def _kind(self) -> str:
        b = self.kind_group.checkedButton()
        return b.property("kind") if b else "expense"   # antes de abrir o formulário pela 1ª vez

    def _load_lists(self, keep_account: int | None = None, keep_dest: int | None = None):
        with Session() as s:
            accs = accounts.list_accounts(s, self.profile.id, include_inactive=True)
            self._contacts = contacts.names(s, self.profile.id)
        self._accounts = {a.id: a for a in accs}
        for box, keep in ((self.account, keep_account), (self.dest, keep_dest)):
            box.clear()
            for a in accs:
                if a.is_active or a.id == keep:
                    box.addItem(a.name + ("" if a.is_active else " (inativa)"), a.id)
        current = self.contact.currentText()
        self.contact.clear()
        self.contact.addItems(self._contacts)
        self.contact.setCurrentText(current)
        self._load_cost_centers(self.cost_center.currentData())

    def _load_cost_centers(self, keep: int | None = None):
        """Só aparece nas edições pagas e quando há centros de custo cadastrados."""
        items = []
        if allowed(current_edition(), "cost_centers"):
            with Session() as s:
                items = cost_centers.choices(s, self.profile.id, keep)
        self.cost_center.clear()
        self.cost_center.addItem("Nenhum", None)
        for cid, name in items:
            self.cost_center.addItem(name, cid)
        self.cost_center.setCurrentIndex(max(0, self.cost_center.findData(keep)) if keep else 0)
        self._has_cc = bool(items)
        self._set_visible(self.cc_box, self._has_cc and self._kind() != "transfer")

    def _load_categories(self, keep: int | None = None):
        with Session() as s:
            items = categories.choices(s, self.profile.id, self._kind()) if self._kind() != "transfer" else []
        self.category.clear()
        self.category.addItem("Sem categoria", None)
        for cid, label in items:
            self.category.addItem(label, cid)
        self.category.setCurrentIndex(max(0, self.category.findData(keep)) if keep else 0)

    def _kind_changed(self):
        k = self._kind()
        transfer = k == "transfer"
        self._set_visible(self.dest_box, transfer)
        self._set_visible(self.category_box, not transfer)
        self._set_visible(self.cc_box, not transfer and self._has_cc)
        self._currency_mode()
        self._set_visible(self.contact_box, not transfer)
        self.account_lbl.label.setText("Da conta" if transfer else "Conta")
        self.paid.setText({"income": "Já foi recebido", "expense": "Já foi pago", "transfer": "Já foi feita"}[k])
        keep = self.category.currentData()
        self._load_categories(keep)
        if transfer and self.dest.currentData() == self.account.currentData() and self.dest.count() > 1:
            self.dest.setCurrentIndex(1 if self.account.currentIndex() == 0 else 0)
        self.desc.setPlaceholderText({"income": "Ex.: Salário", "expense": "Ex.: Conta de luz",
                                      "transfer": "Ex.: Saque para a carteira"}[k])
        self._card_mode()

    def _card(self):
        """A conta escolhida é um cartão com fechamento/vencimento (e não é transferência)?"""
        a = getattr(self, "_accounts", {}).get(self.account.currentData())
        return a if a and a.kind == "card" and a.closing_day and a.due_day and self._kind() != "transfer" else None

    def _currency_mode(self):
        """Mostra a moeda da conta no rótulo do valor e, em transferência entre moedas, o valor que chega."""
        accs = getattr(self, "_accounts", {})
        src, dst = accs.get(self.account.currentData()), accs.get(self.dest.currentData())
        base = self.profile.currency
        cur = src.currency if src else base
        self.amount_lbl.label.setText("Valor" if cur == base else f"Valor ({money.symbol(cur)})")
        cross = self._kind() == "transfer" and src is not None and dst is not None and src.currency != dst.currency
        self._set_visible(self.dest_amount_box, cross)
        if cross:
            self.dest_amount_lbl.label.setText(f"Valor que chega ({money.symbol(dst.currency)})")

    def _card_mode(self):
        """No cartão: a data é a da compra, não há "já foi pago" e mostramos em qual fatura ela cai."""
        card = self._card()
        self.paid_row.setVisible(card is None)
        self.card_info.setVisible(card is not None)
        if card is None:
            self.due_lbl.label.setText("Vencimento")
            return
        self.due_lbl.label.setText("Data da compra")
        _closing, due = cards.statement_for(self.due.date().toPython(), card.closing_day, card.due_day)
        verb = "abate da" if self._kind() == "income" else "vai para a"
        self.card_info.setText(f"No cartão: {verb} fatura {cards.month_label(due)} (vence {due:%d/%m/%Y}). "
                               "Ela é paga pela fatura, em Contas › Faturas.")

    def _update_repeat(self):
        rep = self.repeat.currentData()
        self.times.setVisible(rep != "none")
        self.amount_lbl.label.setText("Valor total" if rep == "installments" else "Valor")
        try:
            value = money.parse(self.amount.text())
        except ValueError:
            value = None
        n = self.times.value()
        start = self.due.date().toPython()
        cur = self.profile.currency
        if rep == "none":
            text = ""
        elif rep == "installments":
            parts = entries.split(value, n) if value and value > 0 else None
            text = (f"{n} parcelas de {money.fmt(parts[-1], cur)}" if parts else f"{n} parcelas") + \
                   f", até {entries.occurrence(start, rep, n - 1).strftime('%d/%m/%Y')}"
            if parts and parts[0] != parts[-1]:
                text += f" (a 1ª com {money.fmt(parts[0], cur)})"
        else:
            text = f"{n} lançamentos, o último em {entries.occurrence(start, rep, n - 1).strftime('%d/%m/%Y')}"
        self.repeat_preview.setText(text)
        self.repeat_preview.setVisible(bool(text))

    # ----- abrir -----
    def open_new(self, default_due: date):
        self.editing = None
        self.title.setText("Novo lançamento")
        self.series_info.hide()
        self._load_lists()
        self.kind_group.button(0).setChecked(True)
        # Conta padrão: a última usada; senão a mais antiga (a criada no primeiro uso).
        ids = [self.account.itemData(i) for i in range(self.account.count())]
        if ids:
            pick = self._last_account if self._last_account in ids else min(ids)
            self.account.setCurrentIndex(ids.index(pick))
        self.category.setCurrentIndex(0)  # não herdar a categoria do último lançamento editado
        self.cost_center.setCurrentIndex(0)
        self._kind_changed()
        self.desc.clear()
        self.amount.clear()
        self.due.setDate(_qdate(default_due))
        self.contact.setCurrentText("")
        self.doc.clear()
        self.dest_amount.clear()
        self.paid.setChecked(False)
        self.paid_date.setDate(_qdate(date.today()))
        self.paid_date.setEnabled(False)
        self.repeat.setCurrentIndex(0)
        self.times.setValue(12)
        self.repeat_frame.show()
        self.attach.set_entry(None)
        self.receipt_btn.hide()
        self.delete_btn.hide()
        self._error(None)
        self._update_repeat()
        for b in self.kind_group.buttons():
            b.setEnabled(True)
        self.desc.setFocus()

    def open_copy(self, e: EntryView):
        """Novo lançamento com os dados de `e` (tipo, descrição, valor, conta, categoria, contato, data)."""
        self.open_new(e.competence_date if e.on_card and e.competence_date else e.due_date)
        self.title.setText("Novo lançamento (cópia)")
        self.kind_group.button(list(entries.KINDS).index(e.kind)).setChecked(True)
        self.account.setCurrentIndex(max(0, self.account.findData(e.account_id)))
        self._kind_changed()
        if e.dest_account_id:
            self.dest.setCurrentIndex(max(0, self.dest.findData(e.dest_account_id)))
        self._load_categories(e.category_id)
        self._load_cost_centers(e.cost_center_id)
        self.desc.setText(e.description)
        self.amount.setText(money.fmt(e.amount, self.profile.currency).split(" ", 1)[1])
        self.contact.setCurrentText(e.contact or "")
        self.desc.setFocus()
        self.desc.selectAll()

    def open_edit(self, e: EntryView):
        self.editing = e
        self.title.setText("Editar lançamento")
        self._load_lists(keep_account=e.account_id, keep_dest=e.dest_account_id)
        self.kind_group.button(list(entries.KINDS).index(e.kind)).setChecked(True)
        self._kind_changed()
        self.desc.setText(e.description)
        self.amount.setText(money.fmt(e.amount, self.profile.currency).split(" ", 1)[1])
        self.due.setDate(_qdate(e.competence_date if e.on_card and e.competence_date else e.due_date))
        self.account.setCurrentIndex(max(0, self.account.findData(e.account_id)))
        if e.dest_account_id:
            self.dest.setCurrentIndex(max(0, self.dest.findData(e.dest_account_id)))
        self._load_categories(e.category_id)
        if e.category_id is None:
            self.category.setCurrentIndex(0)
        self._load_cost_centers(e.cost_center_id)
        self.contact.setCurrentText(e.contact or "")
        self.doc.setText(e.document_no or "")
        self.dest_amount.setText(money.fmt(e.dest_amount, self.profile.currency).split(" ", 1)[1]
                                 if e.dest_amount is not None else "")
        self._currency_mode()
        self.paid.setChecked(e.is_paid)
        self.paid_date.setDate(_qdate(e.paid_date or date.today()))
        self.paid_date.setEnabled(e.is_paid)
        self.repeat_frame.hide()
        self.repeat.setCurrentIndex(0)
        if e.installment:
            self.series_info.setText(f"Parcela {e.installment} de um parcelamento.")
        elif e.is_recurring:
            self.series_info.setText("Lançamento que se repete.")
        self.series_info.setVisible(bool(e.series_id))
        with Session() as s:
            lock = period_lock.locked_through(s, self.profile.id)
        when = e.competence_date or e.due_date
        if lock and when <= lock:
            self.series_info.setText(f"Período fechado até {lock:%d/%m/%Y}: este lançamento não pode ser "
                                     "alterado nem excluído — só dá para marcar o pagamento.")
            self.series_info.show()
        self.delete_btn.setEnabled(not (lock and when <= lock))
        self.attach.set_entry(e.id)
        self.receipt_btn.setVisible(e.kind != "transfer" and not e.on_card)
        self.delete_btn.show()
        self._error(None)
        self.desc.setFocus()

    # ----- salvar/excluir -----
    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def _collect(self) -> EntryData | None:
        try:
            value = money.parse(self.amount.text())
        except ValueError:
            self._error("Valor inválido. Use o formato 1.234,56.")
            self.amount.setFocus()
            return None
        k = self._kind()
        dest_value = None
        if k == "transfer" and not self.dest_amount_box.itemAt(0).widget().isHidden():
            try:
                dest_value = money.parse(self.dest_amount.text()) if self.dest_amount.text().strip() else None
            except ValueError:
                self._error("Valor que chega inválido. Use o formato 1.234,56.")
                self.dest_amount.setFocus()
                return None
        return EntryData(
            kind=k, description=self.desc.text(), amount=value, due_date=self.due.date().toPython(),
            account_id=self.account.currentData(), dest_account_id=self.dest.currentData() if k == "transfer" else None,
            category_id=self.category.currentData() if k != "transfer" else None,
            cost_center_id=self.cost_center.currentData() if k != "transfer" else None,
            contact=self.contact.currentText() if k != "transfer" else None, document_no=self.doc.text(),
            paid=self.paid.isChecked() and self._card() is None,
            paid_date=self.paid_date.date().toPython() if self.paid.isChecked() else None,
            repeat=self.repeat.currentData() if self.editing is None else "none", times=self.times.value(),
            dest_amount=dest_value,
        )

    def _save(self):
        d = self._collect()
        if d is None:
            return
        try:
            with Session() as s:
                if self.editing is None:
                    ids = entries.create(s, self.profile.id, d)
                    sel = ids[0]
                    msg = (f"{len(ids)} lançamentos criados." if len(ids) > 1 else "Lançamento criado.")
                else:
                    scope = "one"
                    following = entries.in_series(s, self.editing.id)
                    if following:
                        scope = ask_scope(self, "Alterar", following)
                        if scope is None:
                            return
                    n = entries.update(s, self.editing.id, d, scope)
                    sel = self.editing.id
                    msg = f"{n} lançamentos alterados." if n > 1 else "Lançamento alterado."
                if d.kind == "expense" and allowed(current_edition(), "budget"):
                    warn = budgets.overspent(s, self.profile.id, d.category_id, d.due_date, self.profile.currency)
                    msg = f"{msg} {warn}" if warn else msg
        except ValueError as e:
            self._error(str(e))
            return
        self._last_account = d.account_id
        self.saved.emit(msg, sel)

    def _delete(self):
        if self.editing is not None and (msg := confirm_delete(self, self.editing)):
            self.saved.emit(msg, 0)


# ---------- página ----------
class EntriesPage(QWidget):
    message = Signal(str)
    import_requested = Signal()
    period_changed = Signal(int, int)    # o próprio Lançamentos mudou o mês (ex.: abrir pelo Dashboard)
    period_locked = Signal(bool)         # "Atrasados" ignora o mês

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile = profile
        self.t = t
        today = date.today()
        self.year, self.month = today.year, today.month
        self.filter = "all"

        # Linha 1: mês, busca, importar
        self.search = QLineEdit(placeholderText="Filtrar este mês…", clearButtonEnabled=True)
        self.search.setToolTip("Filtra a lista do mês. Para procurar em todos os meses, use a busca do topo (Ctrl K).")
        self.search.setMaximumWidth(220)
        self.search.setMinimumWidth(110)
        self.search_icon = self.search.addAction(qta.icon("fa6s.magnifying-glass", color=t["mut"]),
                                                 QLineEdit.LeadingPosition)
        self.ofx_btn = button("Importar OFX", "secondary", t, "fa6s.file-import", "fg")
        self.ofx_btn.setToolTip("Importar o extrato do banco e conciliar (tela Conciliação)")
        row1 = QHBoxLayout()
        row1.setSpacing(theme.SP_S)
        row1.addStretch(1)
        row1.addWidget(self.search, 1)
        row1.addSpacing(theme.SP_S)
        row1.addWidget(self.ofx_btn)
        self.ofx_lock = lock_icon("Importar extrato OFX é um recurso da edição Plus.", t)
        row1.addWidget(self.ofx_lock)
        self.ofx_lock.setVisible(not allowed(current_edition(), "ofx"))
        self.export_btn = button("Exportar", "secondary", t, "fa6s.file-export", "fg")
        self.export_btn.setToolTip("Salvar a lista que está na tela em Excel ou PDF")
        row1.addWidget(self.export_btn)
        if allowed(current_edition(), "export"):
            menu = QMenu(self.export_btn)
            menu.addAction("Excel (.xlsx)", lambda: self._export("xlsx"))
            menu.addAction("PDF", lambda: self._export("pdf"))
            self.export_btn.setMenu(menu)
        else:
            self.export_btn.clicked.connect(lambda: show_upgrade(self, EXPORT_LOCK))
            row1.addWidget(lock_icon(EXPORT_LOCK, t))

        # Linha 2: filtros
        self.filter_group = QButtonGroup(self, exclusive=True)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        for i, (k, label) in enumerate(entries.FILTERS.items()):
            b = QPushButton(label, checkable=True, checked=(k == "all"))
            b.setProperty("variant", "pill")
            b.setProperty("filter", k)
            b.setCursor(Qt.PointingHandCursor)
            self.filter_group.addButton(b, i)
            row2.addWidget(b)
        row2.addStretch(1)
        self.row2 = row2
        self.filters_w = QWidget()
        fw = QHBoxLayout(self.filters_w)
        fw.setContentsMargins(0, 0, 0, 0)
        fw.setSpacing(6)
        self.account_filter = QComboBox()
        self.account_filter.setToolTip("Mostrar só os lançamentos de uma conta (inclui transferências)")
        self.category_filter = QComboBox()
        self.category_filter.setToolTip("Mostrar só uma categoria; escolhendo um grupo, entram as subcategorias")
        for box in (self.account_filter, self.category_filter):
            box.setMinimumWidth(130)
            box.setMaximumWidth(200)
            fw.addWidget(box)
        self.clear_filters = button("Limpar", "link", t, "fa6s.xmark")
        self.clear_filters.setToolTip("Tirar os filtros de conta e categoria")
        self.clear_filters.hide()
        fw.addWidget(self.clear_filters)
        row2.addWidget(self.filters_w)
        self.filters_row = QHBoxLayout()          # usada só em janela estreita
        self.filters_row.setContentsMargins(0, 0, 0, 0)
        self._filters_below = False
        self.filter_group.button(3).setToolTip("Contas em aberto que já venceram, de qualquer mês")
        self.filter_group.button(4).setToolTip("O que foi pago ou recebido neste mês")

        # Tabela
        self.model = EntriesModel(t)
        self.model.currency = profile.currency
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(C_STATUS, StatusDelegate(self.model))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)   # Ctrl/Shift: vários
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setIconSize(QSize(11, 11))
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setSectionResizeMode(QHeaderView.Fixed)
        hdr.setSectionResizeMode(C_DESC, QHeaderView.Stretch)
        for col, w in ((C_KIND, 28), (C_DUE, 70), (C_CONTACT, 140), (C_CAT, 150), (C_ACC, 120),
                       (C_VALUE, 120), (C_STATUS, 96)):
            hdr.resizeSection(col, w)
        hdr.setSortIndicator(C_DUE, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)
        hdr.setToolTip("Clique no título de uma coluna para ordenar")

        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")

        # Totais do mês
        bar = QFrame(objectName="totalsBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(theme.SP_S)
        self.sel_bar = QFrame(objectName="totalsBar")
        sl = QHBoxLayout(self.sel_bar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(theme.SP_M)
        self.sel_lbl = QLabel()
        self.sel_lbl.setFont(theme.mono_font())
        self.pay_sel = button("Marcar como pagos", "secondary", t, "fa6s.circle-check", "pos")
        self.pay_sel.setToolTip("Marca os selecionados como pagos/recebidos hoje.\n"
                                "Compras no cartão ficam de fora: são pagas pela fatura.")
        sl.addWidget(self.sel_lbl)
        sl.addWidget(self.pay_sel)
        sl.addStretch(1)
        self.sel_bar.hide()
        bl.addStretch(1)
        self.tot_rec, self.tot_pay, self.tot_bal = QLabel(), QLabel(), QLabel()
        for label, val, role in (("A receber", self.tot_rec, "total"), ("A pagar", self.tot_pay, "total"),
                                 ("Saldo previsto", self.tot_bal, "accent")):
            bl.addSpacing(theme.SP_L)
            bl.addWidget(QLabel(label))
            val.setFont(theme.mono_font())
            val.setProperty("role", role)
            bl.addWidget(val)
        bl.addWidget(help_icon("Em aberto neste mês: o que ainda vai receber menos o que ainda vai pagar.", t))

        self.left = QWidget()
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(theme.SP_M)
        ll.addLayout(row1)
        ll.addLayout(row2)
        ll.addLayout(self.filters_row)
        self.statements_bar = QLabel(wordWrap=True)
        self.statements_bar.setTextFormat(Qt.RichText)
        self.statements_bar.linkActivated.connect(self._open_statement_link)
        self.statements_bar.hide()
        ll.addWidget(self.statements_bar)
        ll.addWidget(self.table, 1)
        ll.addWidget(self.empty, 1)
        ll.addWidget(self.sel_bar)
        ll.addWidget(bar)

        self.form = EntryForm(profile, t)
        self.form_scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.form_scroll.setWidget(self.form)
        self.form_scroll.setFixedWidth(FORM_W)
        self.form_scroll.hide()

        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addWidget(self.left, 1)
        root.addWidget(self.form_scroll)

        self.search.textChanged.connect(lambda: self.refresh())
        self.filter_group.idClicked.connect(self._filter_changed)
        self.account_filter.activated.connect(lambda _i: self.refresh())
        self.category_filter.activated.connect(lambda _i: self.refresh())
        self.clear_filters.clicked.connect(self._clear_filters)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.pay_sel.clicked.connect(self._pay_selected)
        if allowed(current_edition(), "ofx"):
            self.ofx_btn.clicked.connect(self.import_requested.emit)
        else:
            self.ofx_btn.clicked.connect(lambda: show_upgrade(self, "Importar extrato OFX é um recurso da edição Plus."))
        self.table.doubleClicked.connect(lambda idx: self.edit_entry(idx.data(Qt.UserRole)))
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.form.saved.connect(self._saved)
        self.form.receipt_requested.connect(self.issue_receipt)
        self.form.attach.changed.connect(self._attachments_changed)
        self.form.closed.connect(self.close_form)
        QShortcut(QKeySequence(Qt.Key_Return), self.table, activated=self._edit_current,
                  context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Delete), self.table, activated=self._delete_current,
                  context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)

    # ----- navegação -----
    def set_period(self, year: int, month: int):
        """Mês escolhido no cabeçalho."""
        if (year, month) != (self.year, self.month):
            self.year, self.month = year, month
            self.refresh()

    def _shift_month(self, delta: int):
        y, m = divmod(self.month - 1 + delta, 12)
        self.year, self.month = self.year + y, m + 1
        self.refresh()

    def _go_today(self):
        today = date.today()
        self.year, self.month = today.year, today.month
        self.refresh()

    def _filter_changed(self, i: int):
        self.filter = self.filter_group.button(i).property("filter")
        self.refresh()

    # ----- dados -----
    def refresh(self, select_id: int | None = None):
        if select_id is None:
            cur = self._current()
            select_id = cur.id if cur else None
        self._fill_filters()
        acc_id, cat_id = self.account_filter.currentData(), self.category_filter.currentData()
        self.clear_filters.setVisible(bool(acc_id or cat_id))
        with Session() as s:
            rows = entries.list_entries(s, self.profile.id, year=self.year, month=self.month,
                                        filter=self.filter, search=self.search.text(),
                                        account_id=acc_id, category_id=cat_id)
            totals = entries.month_totals(s, self.profile.id, self.year, self.month)
            first, last = entries.month_range(self.year, self.month)
            sts = cards.due_between(s, self.profile.id, first, last)
        self._show_statements(sts)
        late = self.filter == "late"
        with Session() as s:
            self.model.attached = attachments.counts(s, [e.id for e in rows])
        self.model.set_rows(rows, show_year=late)
        self.period_locked.emit(late)
        self.period_changed.emit(self.year, self.month)
        cur = self.profile.currency
        self.tot_rec.setText(money.fmt(totals.receivable, cur))
        self.tot_pay.setText(money.fmt(totals.payable, cur))
        self.tot_bal.setText(money.fmt(totals.balance, cur))

        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)
        if not rows:
            if self.search.text().strip():
                self.empty.setText("Nada encontrado com essa busca.")
            elif acc_id or cat_id:
                self.empty.setText("Nada neste mês com esses filtros de conta/categoria.")
            elif late:
                self.empty.setText("Nenhuma conta atrasada. Tudo em dia!")
            else:
                self.empty.setText(f"Nenhum lançamento em {MONTHS[self.month - 1]} de {self.year}"
                                   + (" com esse filtro." if self.filter != "all" else
                                      ".\nUse \"Novo lançamento\" (Ctrl+N) para registrar uma receita ou despesa."))
        if select_id:
            for r, e in enumerate(rows):
                if e.id == select_id:
                    self.table.selectRow(r)
                    self.table.scrollTo(self.model.index(r, 0))
                    break
        self._selection_changed()

    def _fill_filters(self):
        """Recarrega as listas de conta/categoria (podem ter mudado), mantendo o que estava escolhido."""
        acc_keep, cat_keep = self.account_filter.currentData(), self.category_filter.currentData()
        with Session() as s:
            accs = accounts.list_accounts(s, self.profile.id)
            tree = categories.tree(s, self.profile.id)
        for box in (self.account_filter, self.category_filter):
            box.blockSignals(True)
            box.clear()
        self.account_filter.addItem("Todas as contas", None)
        for a in accs:
            self.account_filter.addItem(a.name, a.id)
        self.category_filter.addItem("Todas as categorias", None)
        for g in tree:
            self.category_filter.addItem(g.name, g.id)
            for c in g.children:
                self.category_filter.addItem(f"    {c.name}", c.id)
        self.account_filter.setCurrentIndex(max(0, self.account_filter.findData(acc_keep)))
        self.category_filter.setCurrentIndex(max(0, self.category_filter.findData(cat_keep)))
        for box in (self.account_filter, self.category_filter):
            box.blockSignals(False)

    def _clear_filters(self):
        self.account_filter.setCurrentIndex(0)
        self.category_filter.setCurrentIndex(0)
        self.refresh()

    # ----- seleção de vários -----
    def _selected(self) -> list[EntryView]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.rows[r] for r in rows if r < len(self.model.rows)]

    def _selection_changed(self, *_):
        sel = self._selected()
        many = len(sel) > 1
        if many:
            total = sum((e.amount if e.kind == "income" else -e.amount for e in sel if e.kind != "transfer"),
                        Decimal(0))
            self.sel_lbl.setText(f"{len(sel)} selecionados · {money.fmt(total, self.profile.currency)}")
        payable = [e for e in sel if e.status == "pending"]
        self.sel_bar.setVisible(many)
        self.pay_sel.setVisible(bool(payable))
        self.pay_sel.setText(f"Marcar {len(payable)} como pagos" if many else "Marcar como pagos")

    def _pay_selected(self):
        sel = self._selected()
        with Session() as s:
            done, skipped = entries.set_paid_many(s, [e.id for e in sel], date.today())
        msg = f"{done} {'lançamento marcado' if done == 1 else 'lançamentos marcados'} como pagos/recebidos."
        if skipped:
            msg += f" {skipped} ficaram de fora (já pagos ou compras no cartão)."
        self.message.emit(msg)
        self.refresh()

    def export_sheet(self) -> export.Sheet:
        """A lista como está na tela (mês, filtros, busca e ordem)."""
        parts = [f"{MONTHS[self.month - 1].capitalize()} de {self.year}"]
        if self.filter != "all":
            parts.append(entries.FILTERS[self.filter])
        for box in (self.account_filter, self.category_filter):
            if box.currentData():
                parts.append(box.currentText().strip())
        if self.search.text().strip():
            parts.append(f'busca "{self.search.text().strip()}"')
        sheet = export.Sheet("Lançamentos", " · ".join(parts),
                             ["Vencimento", "Pago em", "Descrição", "Contato", "Categoria", "Conta", "Valor",
                              "Situação", "Documento"], currency=self.profile.currency)
        today = date.today()
        for e in self.model.rows:
            sheet.add([e.due_date, e.paid_date,
                       e.description + (f" ({e.installment})" if e.installment else ""), e.contact or "",
                       "Transferência" if e.kind == "transfer" else (e.category or "Sem categoria"),
                       f"{e.account} → {e.dest_account}" if e.kind == "transfer" else e.account,
                       -e.amount if e.kind == "expense" else e.amount, e.status_label(today), e.document_no or ""])
        total = {k: sum((e.amount for e in self.model.rows if e.kind == k), Decimal(0)) for k in ("income", "expense")}
        cur = self.profile.currency
        sheet.footer = (f"{len(self.model.rows)} lançamentos · Receitas {money.fmt(total['income'], cur)} · "
                        f"Despesas {money.fmt(-total['expense'], cur)}")
        return sheet

    def _export(self, kind: str):
        from finora.ui import exporting
        path = exporting.run(self, self.export_sheet(), kind)
        if path:
            self.message.emit(f"Salvo em {path}")

    def _current(self) -> EntryView | None:
        idx = self.table.currentIndex()
        return idx.data(Qt.UserRole) if idx.isValid() and self.model.rows else None

    # ----- formulário -----
    def _default_due(self) -> date:
        today = date.today()
        if (self.year, self.month) == (today.year, today.month):
            return today
        return date(self.year, self.month, min(today.day, calendar.monthrange(self.year, self.month)[1]))

    def new_entry(self):
        self.form.open_new(self._default_due())
        self._show_form(True)

    def open_by_id(self, entry_id: int):
        """Vai para o mês do lançamento e abre-o no formulário (usado pelo Dashboard)."""
        with Session() as s:
            e = entries.get(s, entry_id)
        self.year, self.month = e.due_date.year, e.due_date.month
        self.filter_group.button(0).setChecked(True)
        self.filter = "all"
        self.account_filter.setCurrentIndex(0)
        self.category_filter.setCurrentIndex(0)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.refresh(select_id=e.id)
        self.edit_entry(e)

    def edit_entry(self, e: EntryView | None):
        if e is None:
            return
        self.form.open_edit(e)
        self._show_form(True)

    def issue_receipt(self, e: EntryView):
        """Recibo para imprimir ou salvar em PDF (receita: você assina; despesa: o contato assina)."""
        ReceiptDialog(self, e.id, self.t).exec()

    def duplicate_entry(self, e: EntryView):
        """Abre um lançamento novo já preenchido com os dados deste (nada é salvo até clicar Salvar)."""
        self.form.open_copy(e)
        self._show_form(True)

    def close_form(self):
        self._show_form(False)
        self.table.setFocus()

    def _show_form(self, on: bool):
        self.form_scroll.setVisible(on)
        self._arrange()

    def _arrange(self):
        narrow = self.width() < STACK_BELOW
        self.left.setVisible(not (narrow and self.form_scroll.isVisible()))
        self.form_scroll.setFixedWidth(max(FORM_W, self.width() - 28) if narrow else FORM_W)
        below = self.left.width() < 820
        if below != self._filters_below:
            self._filters_below = below
            (self.row2 if not below else self.filters_row).addWidget(self.filters_w)
            if below:
                self.filters_row.addStretch(1)
            else:
                while self.filters_row.count():
                    self.filters_row.takeAt(0)
        w = self.table.viewport().width() if self.left.isVisible() else self.width() - 28
        for col, min_w in HIDE_WHEN_NARROW:
            self.table.setColumnHidden(col, w < min_w)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._arrange()

    def _attachments_changed(self, msg: str):
        self.message.emit(msg)
        with Session() as s:
            self.model.attached = attachments.counts(s, [e.id for e in self.model.rows])
        self.model.layoutChanged.emit()

    def _saved(self, msg: str, select_id: int):
        self.message.emit(msg)
        self.close_form()
        self.refresh(select_id=select_id or None)

    # ----- ações na tabela -----
    def _edit_current(self):
        self.edit_entry(self._current())

    def _delete_current(self):
        if (e := self._current()) is not None:
            self._delete(e)

    def _delete(self, e: EntryView):
        if msg := confirm_delete(self, e):
            self.message.emit(msg)
            if self.form.editing and self.form.editing.id == e.id:
                self.close_form()
            self.refresh()

    def _toggle_paid(self, e: EntryView):
        with Session() as s:
            entries.set_paid(s, e.id, not e.is_paid, date.today())
        verb = {"income": "recebido", "expense": "pago", "transfer": "feita"}[e.kind]
        self.message.emit(f"\"{e.description}\" marcado como {verb}." if not e.is_paid
                          else f"\"{e.description}\" voltou a ficar em aberto.")
        self.refresh(select_id=e.id)

    def _show_statements(self, sts):
        """Faturas de cartão que vencem no mês, com link para abrir (elas não são linhas da tabela)."""
        if not sts:
            self.statements_bar.hide()
            return
        today, cur, acc = date.today(), self.profile.currency, self.t["acc"]
        parts = [f'<a href="{st.account_id}|{st.due.isoformat()}" style="color:{acc}; text-decoration:none">'
                 f'Fatura {st.account} {st.label}</a> · vence {st.due:%d/%m} · {money.fmt(st.charges, cur)}'
                 f' · {st.status_label(today)}' for st in sts]
        self.statements_bar.setText("Cartão: " + "&nbsp;&nbsp;|&nbsp;&nbsp;".join(parts))
        self.statements_bar.show()

    def _open_statement_link(self, link: str):
        acc_id, due = link.split("|")
        self.open_statement(int(acc_id), date.fromisoformat(due))

    def open_statement(self, account_id: int, due: date | None = None):
        if open_statements(self, account_id, self.profile.currency, self.t, due):
            self.message.emit("Pagamento de fatura registrado.")
        self.refresh()

    def _context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        e: EntryView = idx.data(Qt.UserRole)
        menu = QMenu(self)
        sel = self._selected()
        if len(sel) > 1:                             # vários selecionados
            n = len([x for x in sel if x.status == "pending"])
            act = menu.addAction(qta.icon("fa6s.circle-check", color=self.t["pos"]),
                                 f"Marcar {n} como pagos hoje", self._pay_selected)
            act.setEnabled(n > 0)
            menu.exec(self.table.viewport().mapToGlobal(pos))
            return
        verb = {"income": "recebido", "expense": "pago", "transfer": "feita"}[e.kind]
        if e.on_card:
            menu.addAction(qta.icon("fa6s.file-invoice-dollar", color=self.t["acc"]), "Ver fatura",
                           lambda: self.open_statement(e.account_id, e.due_date))
        else:
            menu.addAction(qta.icon("fa6s.circle-check", color=self.t["pos"]),
                           "Marcar como em aberto" if e.is_paid else f"Marcar como {verb} hoje",
                           lambda: self._toggle_paid(e))
        menu.addAction(qta.icon("fa6s.pen", color=self.t["mut"]), "Editar", lambda: self.edit_entry(e))
        menu.addAction(qta.icon("fa6s.clone", color=self.t["mut"]), "Duplicar", lambda: self.duplicate_entry(e))
        if e.kind != "transfer" and not e.on_card:
            menu.addAction(qta.icon("fa6s.receipt", color=self.t["mut"]), "Emitir recibo…",
                           lambda: self.issue_receipt(e))
        menu.addSeparator()
        menu.addAction(qta.icon("fa6s.trash", color=self.t["neg"]), "Excluir", lambda: self._delete(e))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def apply_theme(self, t: dict):
        self.t = t
        self.form.t = t
        self.form.attach.apply_theme(t)
        self.model.set_theme(t)
        self.search_icon.setIcon(qta.icon("fa6s.magnifying-glass", color=t["mut"]))
