"""Pequenos widgets reutilizáveis."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QHBoxLayout, QWidget
import qtawesome as qta

from finora.ui.theme import SP_S


def help_icon(text: str, t: dict) -> QLabel:
    """Ícone "?" com explicação no tooltip, para termos técnicos."""
    lbl = QLabel()
    lbl.setPixmap(qta.icon("fa6.circle-question", color=t["mut"]).pixmap(QSize(12, 12)))
    lbl.setToolTip(text)
    lbl.setCursor(Qt.WhatsThisCursor)
    return lbl


def field_label(text: str, t: dict, help_text: str | None = None) -> QWidget:
    """Rótulo pequeno acima de um campo, com "?" opcional."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(SP_S)
    lbl = QLabel(text)
    lbl.setProperty("role", "field")
    lay.addWidget(lbl)
    w.label, w.help = lbl, None
    if help_text is not None:
        w.help = help_icon(help_text, t)
        lay.addWidget(w.help)
    lay.addStretch(1)
    return w
