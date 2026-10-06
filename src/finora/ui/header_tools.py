"""Ferramentas do cabeçalho: busca global (Ctrl K) e seletor de período (mês de referência)."""
from datetime import date

from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLabel, QLineEdit, QWidget
import qtawesome as qta

from finora.core.db import Session
from finora.services import search
from finora.ui.widgets import button, themed_icon

MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]
ICONS = {"entry": "fa6s.right-left", "contact": "fa6s.address-book", "account": "fa6s.building-columns",
         "category": "fa6s.tags"}


class GlobalSearch(QLineEdit):
    """Campo de busca com lista de resultados. Escolher um resultado emite `chosen(Hit)`."""
    chosen = Signal(object)

    def __init__(self, t: dict):
        super().__init__(placeholderText="Buscar…  Ctrl K")
        self.setObjectName("globalSearch")
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(150)
        self.setMaximumWidth(260)
        self.setToolTip("Procura em lançamentos (de qualquer mês), contatos, contas e categorias")
        self.entity_id: int | None = None
        self.t = t
        self._icon_action = self.addAction(qta.icon("fa6s.magnifying-glass", color=t["mut"]), QLineEdit.LeadingPosition)
        self.model = QStandardItemModel(self)
        self.completer_ = QCompleter(self.model, self)
        self.completer_.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.completer_.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer_.setMaxVisibleItems(12)
        self.completer_.setWidget(self)
        self.completer_.popup().setIconSize(QSize(12, 12))
        self.completer_.activated[QModelIndex].connect(self._activated)
        self.textEdited.connect(self._search)
        self.hits: list[search.Hit] = []

    def _search(self, text: str):
        self.model.clear()
        if self.entity_id is None or len(text.strip()) < search.MIN_CHARS:
            self.completer_.popup().hide()
            return
        with Session() as s:
            self.hits = search.search(s, self.entity_id, text)
        for h in self.hits:
            it = QStandardItem(qta.icon(ICONS[h.kind], color=self.t["mut"]),
                               f"{h.title}    ·    {search.KINDS[h.kind]} · {h.subtitle}")
            it.setData(h, Qt.UserRole)
            self.model.appendRow(it)
        if not self.hits:
            it = QStandardItem("Nada encontrado")
            it.setEnabled(False)
            self.model.appendRow(it)
        popup = self.completer_.popup()
        popup.setMinimumWidth(max(self.width(), 460))
        self.completer_.complete()

    def _activated(self, index: QModelIndex):
        hit = index.data(Qt.UserRole)
        self.clear()
        self.model.clear()
        if hit is not None:
            self.chosen.emit(hit)

    def focus(self):
        self.setFocus(Qt.ShortcutFocusReason)
        self.selectAll()

    def apply_theme(self, t: dict):
        self.t = t
        self._icon_action.setIcon(qta.icon("fa6s.magnifying-glass", color=t["mut"]))


class PeriodChip(QWidget):
    """‹ Outubro 2026 › Hoje — mês de referência do Dashboard e dos Lançamentos."""
    changed = Signal(int, int)

    def __init__(self, t: dict):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.prev = themed_icon(button("", "icon"), "fa6s.chevron-left", t, "fg", 10)
        self.prev.setToolTip("Mês anterior")
        self.next = themed_icon(button("", "icon"), "fa6s.chevron-right", t, "fg", 10)
        self.next.setToolTip("Próximo mês")
        self.label = QLabel(objectName="monthLabel", alignment=Qt.AlignCenter)
        self.label.setMinimumWidth(120)
        self.compact = False
        self.today_btn = button("Hoje", "link")
        self.today_btn.setToolTip("Voltar para o mês atual")
        for w in (self.prev, self.label, self.next, self.today_btn):
            lay.addWidget(w)
        today = date.today()
        self.year, self.month = today.year, today.month
        self.prev.clicked.connect(lambda: self.shift(-1))
        self.next.clicked.connect(lambda: self.shift(1))
        self.today_btn.clicked.connect(lambda: self.set(date.today().year, date.today().month, emit=True))
        self._update()

    def shift(self, delta: int):
        y, m = divmod(self.month - 1 + delta, 12)
        self.set(self.year + y, m + 1, emit=True)

    def set(self, year: int, month: int, emit: bool = False):
        changed = (year, month) != (self.year, self.month)
        self.year, self.month = year, month
        self._update()
        if emit and changed:
            self.changed.emit(year, month)

    def set_locked(self, locked: bool):
        """Em "Atrasados" o mês não importa (mostra todos)."""
        for w in (self.prev, self.next, self.label, self.today_btn):
            w.setEnabled(not locked)
        self.setToolTip("O filtro Atrasados mostra todos os meses" if locked else "")

    def set_compact(self, compact: bool):
        """Janela estreita: "Set/2026" em vez de "Setembro 2026"."""
        if compact != self.compact:
            self.compact = compact
            self.label.setMinimumWidth(70 if compact else 120)
            self._update()

    def _update(self):
        name = MONTHS[self.month - 1]
        self.label.setText(f"{name[:3].capitalize()}/{self.year}" if self.compact else f"{name.capitalize()} {self.year}")
        self.label.setToolTip(f"{name.capitalize()} de {self.year}")
        today = date.today()
        self.today_btn.setVisible((self.year, self.month) != (today.year, today.month))
