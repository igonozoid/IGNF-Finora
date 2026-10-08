"""Entrar (login) e "Escolha a entidade" — as duas telas antes da janela principal (mockup)."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout,
)
import qtawesome as qta

from finora import __version__
from finora.core.db import Session
from finora.services import users
from finora.services.entity_admin import PERSON_TYPES, EntityView
from finora.services.users import UserView
from finora.ui import theme
from finora.ui.widgets import button, field_label, icon_label


def _brand(t: dict) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(theme.SP_M)
    logo = QLabel("F", alignment=Qt.AlignCenter, objectName="avatar")
    logo.setFixedSize(32, 32)
    row.addWidget(logo)
    col = QVBoxLayout()
    col.setSpacing(0)
    col.addWidget(QLabel("IGNF Finora", objectName="sectionTitle"))
    sub = QLabel(f"Finanças pessoais · v{__version__}")
    sub.setProperty("role", "field")
    col.addWidget(sub)
    row.addLayout(col, 1)
    return row


class LoginDialog(QDialog):
    """E-mail e senha. Devolve o usuário em `self.user`."""

    def __init__(self, t: dict, email: str = "", pin: bool = False):
        super().__init__()
        self.pin = pin                 # um usuário só, com PIN: pede só o PIN
        self.setWindowTitle("IGNF Finora — Entrar")
        self.setWindowIcon(qta.icon("fa6s.coins", color=t["acc"]))
        self.setMinimumWidth(340)
        self.user: UserView | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_L * 2, theme.SP_L * 2, theme.SP_L * 2, theme.SP_L * 2)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(_brand(t))
        lay.addSpacing(theme.SP_M)
        self.email = QLineEdit(email, placeholderText="nome@exemplo.com")
        self.password = QLineEdit(echoMode=QLineEdit.Password, placeholderText="••••••••")
        email_lbl = field_label("E-mail", t)
        lay.addWidget(email_lbl)
        lay.addWidget(self.email)
        lay.addWidget(field_label("PIN" if pin else "Senha", t))
        lay.addWidget(self.password)
        if pin:
            email_lbl.hide()
            self.email.hide()
            self.password.setPlaceholderText("seu PIN")
            self.password.setMaxLength(8)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        self.ok = button("Entrar", "primary")
        self.ok.setDefault(True)
        lay.addWidget(self.ok)
        forgot = button("Esqueci minha senha", "link")
        lay.addWidget(forgot, 0, Qt.AlignCenter)
        self.ok.clicked.connect(self._enter)
        self.password.returnPressed.connect(self._enter)
        self.email.returnPressed.connect(self.password.setFocus)
        forgot.clicked.connect(self._forgot)
        (self.password if email or pin else self.email).setFocus()

    def _enter(self):
        try:
            with Session() as s:
                self.user = (users.authenticate_pin(s, self.password.text()) if self.pin else
                             users.authenticate(s, self.email.text(), self.password.text()))
        except ValueError as e:
            self.error.setText(str(e))
            self.error.show()
            self.password.selectAll()
            self.password.setFocus()
            return
        self.accept()

    def _forgot(self):
        QMessageBox.information(self, "Esqueci minha senha",
                                "A senha fica só neste computador (ou no servidor da sua rede), por segurança.\n\n"
                                "Peça a um administrador do Finora para criar uma senha nova para você em "
                                "Administração › Usuários.")


class EntityChooser(QDialog):
    """Lista as entidades que o usuário pode abrir. Devolve o id em `self.entity_id`."""

    def __init__(self, items: list[EntityView], t: dict, current: int | None = None):
        super().__init__()
        self.setWindowTitle("IGNF Finora — Escolha a entidade")
        self.setWindowIcon(qta.icon("fa6s.coins", color=t["acc"]))
        self.setMinimumSize(420, 360)
        self.entity_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_L * 2, theme.SP_L * 2, theme.SP_L * 2, theme.SP_L * 2)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(_brand(t))
        lay.addSpacing(theme.SP_S)
        lay.addWidget(QLabel("Escolha a entidade", objectName="sectionTitle"))
        hint = QLabel("Cada empresa ou pessoa tem dados totalmente separados.", wordWrap=True)
        hint.setProperty("role", "muted")
        lay.addWidget(hint)
        self.list = QListWidget(objectName="contactList")
        self.list.setIconSize(QSize(14, 14))
        for e in items:
            icon = qta.icon("fa6s.building" if e.person_type == "PJ" else "fa6s.user", color=t["acc"])
            sub = " · ".join(x for x in (PERSON_TYPES.get(e.person_type, ""), e.document_fmt, e.currency) if x)
            it = QListWidgetItem(icon, f"{e.name}\n{sub}")
            it.setData(Qt.UserRole, e.id)
            it.setSizeHint(QSize(0, 44))
            self.list.addItem(it)
            if e.id == current:
                self.list.setCurrentItem(it)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancelar", "secondary")
        ok = button("Abrir", "primary")
        ok.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._open)
        self.list.itemDoubleClicked.connect(lambda _i: self._open())

    def _open(self):
        it = self.list.currentItem()
        if it is None:
            return
        self.entity_id = it.data(Qt.UserRole)
        self.accept()
