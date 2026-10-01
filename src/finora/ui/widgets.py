"""Pequenos widgets reutilizáveis."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QHBoxLayout, QMessageBox, QPushButton, QWidget
import qtawesome as qta

from finora.ui.theme import SP_M, SP_S

UPGRADE_TEXT = (
    "Esse recurso faz parte das edições pagas do IGNF Finora.\n\n"
    "Plus: contas ilimitadas, importação de extrato (OFX), anexos, orçamento e exportação.\n"
    "Pro: tudo do Plus + contas em outras moedas e várias entidades.\n\n"
    "A ativação da licença chega em breve, em Configurações."
)


def _paint(w: QWidget, t: dict) -> None:
    name, key, px = w.property("qtaIcon").split("|")
    if isinstance(w, QAbstractButton):
        w.setIcon(qta.icon(name, color=t[key], color_active=t["fg"]))
        w.setIconSize(QSize(int(px), int(px)))
    else:
        w.setPixmap(qta.icon(name, color=t[key]).pixmap(QSize(int(px), int(px))))


def themed_icon(w: QWidget, name: str, t: dict, key: str = "mut", px: int = 12) -> QWidget:
    """Põe um ícone qtawesome num QLabel/botão e guarda a receita para `retheme`."""
    w.setProperty("qtaIcon", f"{name}|{key}|{px}")
    _paint(w, t)
    return w


def retheme(root: QWidget, t: dict) -> None:
    """Redesenha, com as cores do novo tema, todos os ícones criados por `themed_icon`."""
    for w in root.findChildren(QWidget):
        if w.property("qtaIcon"):
            _paint(w, t)


def icon_label(name: str, t: dict, key: str = "mut", px: int = 12) -> QLabel:
    return themed_icon(QLabel(), name, t, key, px)


def help_icon(text: str, t: dict) -> QLabel:
    """Ícone "?" com explicação no tooltip, para termos técnicos."""
    lbl = icon_label("fa6.circle-question", t)
    lbl.setToolTip(text)
    lbl.setCursor(Qt.WhatsThisCursor)
    return lbl


def lock_icon(text: str, t: dict) -> QLabel:
    """Cadeado de recurso pago, com explicação no tooltip."""
    lbl = icon_label("fa6s.lock", t, "acc", 11)
    lbl.setToolTip(text)
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


def button(text: str, variant: str, t: dict | None = None, icon: str | None = None, color_key: str = "mut") -> QPushButton:
    b = QPushButton(text)
    b.setProperty("variant", variant)
    b.setCursor(Qt.PointingHandCursor)
    if icon and t:
        themed_icon(b, icon, t, color_key, 11)
    return b


def show_upgrade(parent, reason: str) -> None:
    QMessageBox.information(parent, "Recurso das edições pagas", f"{reason}\n\n{UPGRADE_TEXT}")


def upgrade_box(reason: str, t: dict, parent=None) -> QFrame:
    """Aviso de limite da edição Free, com cadeado e convite para upgrade."""
    box = QFrame(objectName="lockBox")
    lay = QHBoxLayout(box)
    lay.setContentsMargins(SP_M + 2, SP_M, SP_M + 2, SP_M)
    lay.setSpacing(SP_M)
    icon = icon_label("fa6s.lock", t, "acc", 14)
    text = QLabel(reason, wordWrap=True)
    more = button("Conhecer o Plus", "secondary")
    more.clicked.connect(lambda: show_upgrade(parent or box, reason))
    lay.addWidget(icon)
    lay.addWidget(text, 1)
    lay.addWidget(more)
    return box
