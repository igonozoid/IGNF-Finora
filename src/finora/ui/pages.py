"""Telas do app. Por enquanto, todas mostram um aviso de 'em construção'."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QWidget, QFrame, QLabel, QVBoxLayout
import qtawesome as qta

from finora.ui.theme import SP_M, SP_L


class PlaceholderPage(QWidget):
    def __init__(self, icon: str, title: str, text: str, parent=None):
        super().__init__(parent)
        self._icon_name = icon
        self.setObjectName("content")

        card = QFrame(objectName="emptyCard")
        card.setFixedWidth(420)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(SP_L * 2, SP_L * 2, SP_L * 2, SP_L * 2)
        lay.setSpacing(SP_M)

        self._icon = QLabel(alignment=Qt.AlignCenter)
        t = QLabel(title, objectName="emptyTitle", alignment=Qt.AlignCenter)
        d = QLabel(text, objectName="emptyText", alignment=Qt.AlignCenter, wordWrap=True)
        for w in (self._icon, t, d):
            lay.addWidget(w)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, SP_L, 14, SP_L)
        outer.addWidget(card, alignment=Qt.AlignCenter)

    def apply_theme(self, t: dict):
        self._icon.setPixmap(qta.icon(self._icon_name, color=t["mut"]).pixmap(QSize(32, 32)))
