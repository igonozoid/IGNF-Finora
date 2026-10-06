"""Pequenos widgets reutilizáveis."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QLabel, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
import qtawesome as qta

from finora.ui.theme import SP_M, SP_S

UPGRADE_TEXT = (
    "Esse recurso faz parte das edições pagas do IGNF Finora.\n\n"
    "Plus: todos os recursos (contas ilimitadas, várias moedas, OFX, anexos, orçamento, exportação,\n"
    "rede local…) para até 3 usuários e 10 entidades.\n"
    "Pro: tudo do Plus, com usuários e entidades ilimitados.\n\n"
    "Já tem uma chave? Cole em Configurações › Sua edição."
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


def set_tone(w: QWidget, tone: str | None) -> None:
    """Cor semântica de um texto ('pos', 'neg', 'mut' ou None), resolvida pelo QSS do tema."""
    w.setProperty("tone", tone or "")
    w.style().unpolish(w)
    w.style().polish(w)


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


class WrapFrame(QFrame):
    """QFrame com texto que quebra linha. Dentro de área com rolagem o Qt não considera a altura do texto
    quebrado no espaço mínimo e espreme o quadro; aqui a altura necessária vira mínimo a cada largura."""

    def resizeEvent(self, e):
        super().resizeEvent(e)
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            need = lay.totalHeightForWidth(self.width())
            if need != self.minimumHeight():
                self.setMinimumHeight(need)


def upgrade_box(reason: str, t: dict, parent=None, compact: bool = False) -> QFrame:
    """Aviso de limite da edição Free, com cadeado e convite para upgrade.
    `compact`: botão embaixo do texto, para painéis estreitos."""
    box = WrapFrame(objectName="lockBox")
    outer = QVBoxLayout(box)
    outer.setContentsMargins(SP_M + 2, SP_M, SP_M + 2, SP_M)
    outer.setSpacing(SP_M)
    lay = QHBoxLayout()
    lay.setSpacing(SP_M)
    icon = icon_label("fa6s.lock", t, "acc", 14)
    text = QLabel(reason, wordWrap=True)
    more = button("Conhecer o Plus", "secondary")
    more.clicked.connect(lambda: show_upgrade(parent or box, reason))
    lay.addWidget(icon, 0, Qt.AlignTop if compact else Qt.AlignVCenter)
    lay.addWidget(text, 1)
    outer.addLayout(lay)
    if compact:
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(more)
        outer.addLayout(row)
    else:
        lay.addWidget(more)
    return box
