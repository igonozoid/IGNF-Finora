"""Configurações: backup e restauração, aparência, edição e informações do app."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QScrollArea,
    QVBoxLayout, QWidget,
)

from finora import __version__
from finora.core import db, licensing, settings
from finora.core.license_key import LicenseError
from finora.core.licensing import allowed, current_edition
from finora.services import backup
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, help_icon, icon_label, set_tone, show_upgrade, upgrade_box

MAX_W = 680
OLD_BACKUP_DAYS = 30
CLOUD_MSG = "Backup automático na nuvem é um recurso da edição Plus."


def _section(title: str, icon: str, t: dict) -> tuple[QFrame, QVBoxLayout]:
    box = QFrame(objectName="card")
    box.setMaximumWidth(MAX_W)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, theme.SP_L, 14, 14)
    lay.setSpacing(theme.SP_M)
    head = QHBoxLayout()
    head.setSpacing(6)
    head.addWidget(icon_label(icon, t, "acc", 12))
    head.addWidget(QLabel(title, objectName="sectionTitle"))
    head.addStretch(1)
    lay.addLayout(head)
    return box, lay


def _muted(text: str) -> QLabel:
    lbl = QLabel(text, wordWrap=True)
    lbl.setProperty("role", "muted")
    return lbl


def _open_folder(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SettingsPage(QWidget):
    message = Signal(str)
    theme_requested = Signal(str)
    nav_requested = Signal(str)
    restart_requested = Signal()

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t

        body = QWidget(objectName="pageBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(theme.SP_L)
        bl.addWidget(self._backup_section())
        bl.addWidget(self._appearance_section())
        bl.addWidget(self._edition_section())
        bl.addWidget(self._about_section())
        bl.addStretch(1)
        scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.addWidget(scroll)

    # ---------- backup ----------
    def _backup_section(self) -> QFrame:
        box, lay = _section("Backup e restauração", "fa6s.shield-halved", self.t)
        lay.addWidget(_muted("Seus dados ficam só neste computador. Faça um backup de vez em quando e guarde "
                             "a cópia fora dele: num pendrive, no Google Drive, OneDrive…"))
        self.last_lbl = QLabel(wordWrap=True)
        lay.addWidget(self.last_lbl)

        row = QHBoxLayout()
        row.setSpacing(theme.SP_M)
        self.backup_btn = button("Fazer backup agora", "primary")
        self.restore_btn = button("Restaurar de um arquivo…", "secondary", self.t, "fa6s.clock-rotate-left", "fg")
        row.addWidget(self.backup_btn)
        row.addWidget(self.restore_btn)
        row.addStretch(1)
        lay.addLayout(row)

        auto = QHBoxLayout()
        auto.setSpacing(6)
        self.auto_chk = QCheckBox("Backup automático diário neste computador (guarda os últimos 7)")
        self.auto_chk.setChecked(settings.get_auto_backup())
        auto.addWidget(self.auto_chk)
        auto.addWidget(help_icon("Feito ao abrir o app, uma vez por dia, na pasta de dados do Finora.\n"
                                 "Ajuda a desfazer um erro, mas não protege se o computador estragar:\n"
                                 "por isso faça também o backup manual e guarde fora dele.", self.t))
        auto.addStretch(1)
        lay.addLayout(auto)

        head = QHBoxLayout()
        sub = QLabel("Backups neste computador", objectName="sectionTitle")
        head.addWidget(sub)
        head.addStretch(1)
        open_btn = button("Abrir pasta", "link", self.t, "fa6s.folder-open")
        open_btn.clicked.connect(lambda: _open_folder(db.BACKUP_DIR))
        head.addWidget(open_btn)
        lay.addSpacing(theme.SP_S)
        lay.addLayout(head)
        self.local_rows = QVBoxLayout()
        self.local_rows.setSpacing(0)
        lay.addLayout(self.local_rows)

        if not allowed(current_edition(), "cloud_backup"):
            lay.addSpacing(theme.SP_S)
            lay.addWidget(upgrade_box("Backup automático na nuvem, para não perder nada nem se o computador "
                                      "estragar, faz parte da edição Plus.", self.t, self))

        self.backup_btn.clicked.connect(self._backup_now)
        self.restore_btn.clicked.connect(self._restore_file)
        self.auto_chk.toggled.connect(self._toggle_auto)
        return box

    def _refresh_backup(self):
        last = settings.get_last_backup()
        if last:
            when = datetime.fromisoformat(last)
            days = (datetime.now() - when).days
            self.last_lbl.setText(f"Último backup manual: {when:%d/%m/%Y} às {when:%H:%M}"
                                  + (f" — já faz {days} dias." if days >= OLD_BACKUP_DAYS else "."))
            set_tone(self.last_lbl, "neg" if days >= OLD_BACKUP_DAYS else None)
        else:
            self.last_lbl.setText("Você ainda não fez nenhum backup manual.")
            set_tone(self.last_lbl, "neg")

        while self.local_rows.count():
            w = self.local_rows.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        items = backup.list_local()[:8]
        for b in items:
            self.local_rows.addWidget(self._local_row(b))
        if not items:
            self.local_rows.addWidget(_muted("Nenhum ainda. O primeiro automático é feito na próxima abertura."))

    def _local_row(self, b: backup.BackupInfo) -> QFrame:
        row = QFrame(objectName="listRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 5, 0, 5)
        lay.setSpacing(theme.SP_M)
        when = QLabel(f"{b.modified:%d/%m/%Y %H:%M}")
        when.setFont(theme.mono_font())
        when.setFixedWidth(120)
        kind = "Antes de restaurar" if b.path.name.startswith(backup.SAFETY_PREFIX) else "Automático"
        what = QLabel(f"{kind} · {b.accounts} {'conta' if b.accounts == 1 else 'contas'} · "
                      f"{b.entries} {'lançamento' if b.entries == 1 else 'lançamentos'}")
        what.setMinimumWidth(1)
        what.setToolTip(str(b.path))
        size = QLabel(b.size_label)
        size.setProperty("role", "field")
        rb = button("Restaurar", "link", self.t, "fa6s.clock-rotate-left")
        rb.clicked.connect(lambda: self._restore(b.path))
        lay.addWidget(when)
        lay.addWidget(what, 1)
        lay.addWidget(size)
        lay.addWidget(rb)
        return row

    def _start_folder(self) -> str:
        return settings.get_backup_folder() or QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)

    def _backup_now(self):
        start = str(Path(self._start_folder()) / backup.suggested_name())
        path, _ = QFileDialog.getSaveFileName(self, "Salvar backup", start, "Backup do Finora (*.db)")
        if not path:
            return
        try:
            dest = backup.backup_to(Path(path))
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Backup", f"Não foi possível salvar o backup.\n\n{e}")
            return
        settings.set_backup_folder(str(dest.parent))
        settings.set_last_backup(datetime.now().isoformat(timespec="minutes"))
        self.message.emit(f"Backup salvo em {dest}")
        self._refresh_backup()

    def _restore_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Escolher backup", self._start_folder(),
                                              "Backup do Finora (*.db);;Todos os arquivos (*)")
        if path:
            self._restore(Path(path))

    def _restore(self, path: Path):
        try:
            info = backup.inspect_backup(path)
        except ValueError as e:
            QMessageBox.warning(self, "Restaurar backup", str(e))
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Restaurar backup")
        box.setText("Trocar os dados atuais por este backup?")
        box.setInformativeText(
            f"Perfil: {info.name}\n"
            f"{info.accounts} {'conta' if info.accounts == 1 else 'contas'} · "
            f"{info.entries} {'lançamento' if info.entries == 1 else 'lançamentos'}\n"
            f"Arquivo de {info.modified:%d/%m/%Y às %H:%M}\n\n"
            "Antes de trocar, uma cópia dos dados atuais fica guardada em "
            "\"Backups neste computador\", caso queira voltar atrás.")
        ok = box.addButton("Restaurar", QMessageBox.AcceptRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not ok:
            return
        try:
            backup.restore_from(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Restaurar backup", f"Não foi possível restaurar.\n\n{e}")
            return
        QMessageBox.information(self, "Restaurar backup", "Backup restaurado. O IGNF Finora vai reabrir agora.")
        self.restart_requested.emit()

    def _toggle_auto(self, on: bool):
        settings.set_auto_backup(on)
        self.message.emit("Backup automático ligado." if on else "Backup automático desligado.")

    # ---------- aparência ----------
    def _appearance_section(self) -> QFrame:
        box, lay = _section("Aparência", "fa6s.palette", self.t)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tema"))
        self.theme_box = QComboBox()
        self.theme_box.addItem("Claro", "light")
        self.theme_box.addItem("Escuro", "dark")
        self.theme_box.setMinimumWidth(140)
        row.addWidget(self.theme_box)
        row.addWidget(_muted("Atalho: Ctrl+T"))
        row.addStretch(1)
        lay.addLayout(row)
        self.theme_box.activated.connect(lambda i: self.theme_requested.emit(self.theme_box.itemData(i)))

        nav = QHBoxLayout()
        lbl = QLabel("Menu")
        lbl.setMinimumWidth(QLabel("Tema").sizeHint().width())
        nav.addWidget(lbl)
        self.nav_box = QComboBox()
        for k, label in settings.NAV_MODES.items():
            self.nav_box.addItem(label, k)
        self.nav_box.setMinimumWidth(140)
        nav.addWidget(self.nav_box)
        nav.addWidget(help_icon("Como as seções do app aparecem:\n"
                                "Barra lateral: ícone e nome à esquerda.\n"
                                "Só ícones: barra fina à esquerda, sobra mais espaço (bom para telas pequenas).\n"
                                "Abas no topo: as seções ficam em abas abaixo do título.", self.t))
        nav.addStretch(1)
        lay.addLayout(nav)
        self.nav_box.activated.connect(lambda i: self.nav_requested.emit(self.nav_box.itemData(i)))
        return box

    def set_nav_name(self, mode: str):
        self.nav_box.setCurrentIndex(max(0, self.nav_box.findData(mode)))

    def set_theme_name(self, name: str):
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(name)))

    # ---------- edição ----------
    def _edition_section(self) -> QFrame:
        box, lay = _section("Sua edição", "fa6s.key", self.t)
        lic = licensing.current_license()
        stored = licensing.stored_license()
        if lic:
            title = QLabel(f"Edição {lic.edition.capitalize()} · licenciada para {lic.name}")
            title.setObjectName("sectionTitle")
            lay.addWidget(title)
            lay.addWidget(_muted(f"Válida até {lic.expires:%d/%m/%Y}." if lic.expires
                                 else "Licença sem data de vencimento."))
        else:
            lay.addWidget(QLabel("Edição Free"))
            if stored is not None:   # tinha licença, mas venceu
                gone = QLabel(f"Sua licença {stored.edition.capitalize()} venceu em {stored.expires:%d/%m/%Y}. "
                              "Você voltou para a Free; seus dados continuam todos aqui.", wordWrap=True)
                set_tone(gone, "neg")
                lay.addWidget(gone)
            lay.addWidget(_muted("Na Free você tem lançamentos, até 3 contas, Dashboard, DRE pessoal, fluxo de "
                                 "caixa e backup. Comprou o Plus ou o Pro? Cole abaixo a chave que recebeu."))

        # Ativar / trocar chave
        self.key_box = QWidget()
        kl = QVBoxLayout(self.key_box)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setSpacing(6)
        self.key_edit = QPlainTextEdit(placeholderText="Cole aqui sua chave de licença (começa com FNR1-)")
        self.key_edit.setFont(theme.mono_font())
        self.key_edit.setFixedHeight(58)
        kl.addWidget(self.key_edit)
        self.key_error = QLabel(wordWrap=True)
        self.key_error.setProperty("role", "error")
        self.key_error.hide()
        kl.addWidget(self.key_error)
        krow = QHBoxLayout()
        activate = button("Ativar licença", "primary")
        from_file = button("Abrir arquivo da chave…", "link", self.t, "fa6s.file-import")
        krow.addWidget(activate)
        krow.addWidget(from_file)
        krow.addStretch(1)
        kl.addLayout(krow)
        lay.addWidget(self.key_box)
        activate.clicked.connect(self._activate)
        from_file.clicked.connect(self._key_from_file)

        row = QHBoxLayout()
        if lic:
            self.key_box.hide()
            change = button("Trocar chave", "secondary")
            change.clicked.connect(lambda: (self.key_box.show(), self.key_edit.setFocus()))
            remove = button("Remover licença", "danger")
            remove.clicked.connect(self._deactivate)
            row.addWidget(change)
            row.addStretch(1)
            row.addWidget(remove)
        else:
            more = button("Conhecer as edições pagas", "secondary")
            more.clicked.connect(lambda: show_upgrade(self, "Compare o que cada edição oferece."))
            row.addWidget(more)
            row.addStretch(1)
        lay.addLayout(row)
        return box

    def _key_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir chave de licença", self._start_folder(),
                                              "Chave de licença (*.txt *.lic *.key);;Todos os arquivos (*)")
        if path:
            try:
                self.key_edit.setPlainText(Path(path).read_text(encoding="utf-8", errors="ignore").strip())
            except OSError as e:
                self._key_err(f"Não foi possível ler o arquivo: {e}")
                return
            self._activate()

    def _key_err(self, msg: str | None):
        self.key_error.setText(msg or "")
        self.key_error.setVisible(bool(msg))

    def _activate(self):
        key = self.key_edit.toPlainText().strip()
        if not key:
            self._key_err("Cole a chave que você recebeu por e-mail.")
            return
        try:
            lic = licensing.activate(key)
        except LicenseError as e:
            self._key_err(str(e))
            return
        self._key_err(None)
        QMessageBox.information(self, "Licença ativada",
                                f"Edição {lic.edition.capitalize()} ativada para {lic.name}.\n"
                                "O IGNF Finora vai reabrir para liberar os recursos.")
        self.restart_requested.emit()

    def _deactivate(self):
        if QMessageBox.question(self, "Remover licença",
                                "Remover a licença deste computador? O app volta para a edição Free "
                                "(seus dados continuam todos aqui). Guarde a chave para ativar de novo.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        licensing.deactivate()
        self.restart_requested.emit()

    # ---------- sobre ----------
    def _about_section(self) -> QFrame:
        box, lay = _section("Sobre", "fa6s.circle-info", self.t)
        lay.addWidget(QLabel(f"IGNF Finora · versão {__version__}"))
        row = QHBoxLayout()
        path = QLabel(f"Pasta dos dados: {db.DATA_DIR}")
        path.setProperty("role", "muted")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setMinimumWidth(1)
        row.addWidget(path, 1)
        open_btn = button("Abrir pasta", "link", self.t, "fa6s.folder-open")
        open_btn.clicked.connect(lambda: _open_folder(db.DATA_DIR))
        row.addWidget(open_btn)
        lay.addLayout(row)
        return box

    # ---------- página ----------
    def refresh(self):
        self._refresh_backup()

    def apply_theme(self, t: dict):
        self.t = t
