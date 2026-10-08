"""Configurações: backup e restauração, aparência, edição e informações do app."""
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)

from finora import __version__
from finora.core import db, licensing, settings
from finora.core.logs import log
from finora.core.license_key import LicenseError
from finora.core.licensing import allowed, current_edition
from finora.core import money
from finora.core.db import Session
from finora.services import backup, period_lock, setup
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import WrapFrame, button, help_icon, icon_label, set_tone, show_upgrade, upgrade_box

MAX_W = 680
OLD_BACKUP_DAYS = 30
CLOUD_MSG = "Backup automático na nuvem é um recurso da edição Plus."


def _section(title: str, icon: str, t: dict) -> tuple[QFrame, QVBoxLayout]:
    box = WrapFrame(objectName="card")       # altura mínima acompanha o texto que quebra linha e as listas
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


def _fit_list(box: QWidget) -> None:
    """Lista que muda de tamanho dentro de um quadro com texto que quebra linha: com altura fixa, o Qt não
    espreme as linhas (a conta de altura pela largura ignorava a lista e cortava os itens)."""
    lay = box.layout()
    box.setFixedHeight(sum(lay.itemAt(i).widget().sizeHint().height() if lay.itemAt(i).widget() else 0
                           for i in range(lay.count())))
    card = box.parentWidget()
    if isinstance(card, WrapFrame) and card.width():                 # recalcula já, sem esperar redimensionar
        card.setMinimumHeight(card.layout().totalHeightForWidth(card.width()))


def _open_folder(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SettingsPage(QWidget):
    message = Signal(str)
    theme_requested = Signal(str)
    nav_requested = Signal(str)
    profile_changed = Signal(object)
    restart_requested = Signal()

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t

        body = QWidget(objectName="pageBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(theme.SP_L)
        from finora.ui.currencies_section import CurrenciesSection
        self.currencies = CurrenciesSection(profile.id, profile.currency, t, MAX_W)
        self.currencies.message.connect(self.message.emit)
        # seções que só quem administra vê (perfil, moedas, backup, fechamento e licença)
        from finora.ui.data_location_section import DataLocationSection
        self.data_location = DataLocationSection(t, MAX_W)
        self.data_location.message.connect(self.message.emit)
        self.data_location.restart_requested.connect(self.restart_requested.emit)
        self.admin_sections = [self._profile_section(), self.data_location, self.currencies,
                               self._backup_section(), self._lock_section()]
        for w in self.admin_sections:
            bl.addWidget(w)
        bl.addWidget(self._appearance_section())
        edition = self._edition_section()
        self.admin_sections.append(edition)
        bl.addWidget(edition)
        bl.addWidget(self._about_section())
        bl.addStretch(1)
        scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        self.body = body
        root = QVBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.addWidget(scroll)

    # ---------- perfil ----------
    def _profile_section(self) -> QFrame:
        box, lay = _section("Seu perfil", "fa6s.user", self.t)
        form = QGridLayout()
        form.setHorizontalSpacing(theme.SP_M)
        form.setVerticalSpacing(6)
        self.name_edit = QLineEdit(maxLength=120)
        self.currency_box = QComboBox()
        for code, (sym, label) in money.CURRENCIES.items():
            self.currency_box.addItem(f"{label} ({sym})", code)
        form.addWidget(QLabel("Nome"), 0, 0)
        form.addWidget(self.name_edit, 0, 1)
        cur_lbl = QHBoxLayout()
        cur_lbl.setSpacing(4)
        cur_lbl.addWidget(QLabel("Moeda principal"))
        cur_lbl.addWidget(help_icon("A moeda em que você recebe e gasta no dia a dia.\n"
                                    "Os relatórios e o saldo total usam essa moeda.", self.t))
        form.addLayout(cur_lbl, 1, 0)
        form.addWidget(self.currency_box, 1, 1)
        form.setColumnStretch(1, 1)
        lay.addLayout(form)

        self.accounts_too = QCheckBox("Trocar também a moeda das contas que usam a moeda atual")
        self.accounts_too.setChecked(True)
        self.accounts_too.setVisible(False)
        lay.addWidget(self.accounts_too)
        self.currency_note = QLabel(wordWrap=True)
        set_tone(self.currency_note, "neg")
        self.currency_note.hide()
        lay.addWidget(self.currency_note)
        self.profile_error = QLabel(wordWrap=True)
        self.profile_error.setProperty("role", "error")
        self.profile_error.hide()
        lay.addWidget(self.profile_error)

        row = QHBoxLayout()
        self.profile_save = button("Salvar perfil", "primary")
        row.addWidget(self.profile_save)
        row.addStretch(1)
        lay.addLayout(row)

        self.name_edit.textChanged.connect(self._profile_dirty)
        self.currency_box.currentIndexChanged.connect(self._profile_dirty)
        self.name_edit.returnPressed.connect(self._save_profile)
        self.profile_save.clicked.connect(self._save_profile)
        self._load_profile()
        return box

    def _load_profile(self):
        self.name_edit.setText(self.profile.name)
        self.currency_box.setCurrentIndex(max(0, self.currency_box.findData(self.profile.currency)))
        self._profile_dirty()

    def _profile_dirty(self):
        new_cur = self.currency_box.currentData()
        changing = new_cur != self.profile.currency
        multi = allowed(current_edition(), "multi_currency")
        self.accounts_too.setVisible(changing and bool(multi))
        if changing:
            old_sym, new_sym = money.symbol(self.profile.currency), money.symbol(new_cur)
            self.currency_note.setText(
                f"Atenção: os valores não são convertidos. {old_sym} 100,00 passa a aparecer como "
                f"{new_sym} 100,00." + ("" if multi else " Na Free todas as contas usam a moeda principal, "
                                                        "então elas mudam junto."))
        self.currency_note.setVisible(changing)
        self.profile_save.setEnabled(changing or self.name_edit.text().strip() != self.profile.name)
        self.profile_error.hide()

    def _save_profile(self):
        try:
            with Session() as s:
                profile, changed = setup.update_profile(
                    s, self.profile.id, name=self.name_edit.text(), currency=self.currency_box.currentData(),
                    accounts_too=self.accounts_too.isChecked())
        except ValueError as e:
            self.profile_error.setText(str(e))
            self.profile_error.show()
            return
        log.info("Perfil atualizado (moeda %s; %d contas mudaram de moeda)", profile.currency, changed)
        self.profile = profile
        self._load_profile()
        self.currencies.set_base(profile.currency)
        self.profile_changed.emit(profile)
        extra = f" {changed} {'conta mudou' if changed == 1 else 'contas mudaram'} de moeda." if changed else ""
        self.message.emit("Perfil atualizado." + extra)

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
        self.local_box = QWidget()                # altura fixa, calculada ao preencher (ver _fit_list)
        self.local_rows = QVBoxLayout(self.local_box)
        self.local_rows.setContentsMargins(0, 0, 0, 0)
        self.local_rows.setSpacing(0)
        lay.addWidget(self.local_box)

        lay.addSpacing(theme.SP_S)
        if not allowed(current_edition(), "cloud_backup"):
            self.cloud_box = None
            lay.addWidget(upgrade_box("Backup automático na nuvem, para não perder nada nem se o computador "
                                      "estragar, faz parte da edição Plus.", self.t, self))
        else:
            self._cloud_ui(lay)

        self.backup_btn.clicked.connect(self._backup_now)
        self.restore_btn.clicked.connect(self._restore_file)
        self.auto_chk.toggled.connect(self._toggle_auto)
        return box

    def _cloud_ui(self, lay: QVBoxLayout):
        head = QHBoxLayout()
        head.addWidget(QLabel("Backup na nuvem", objectName="sectionTitle"))
        head.addWidget(help_icon("Ao fechar o app, uma cópia do dia vai para a pasta do OneDrive, Google Drive ou\n"
                                 "Dropbox deste computador, e o programa da nuvem envia para a sua conta.\n"
                                 f"Ficam os últimos {backup.KEEP_CLOUD} dias. Para restaurar em outro computador,\n"
                                 "instale o Finora, escolha a mesma pasta e clique em Restaurar.", self.t))
        head.addStretch(1)
        self.cloud_open = button("Abrir pasta", "link", self.t, "fa6s.folder-open")
        self.cloud_open.clicked.connect(
            lambda: _open_folder(Path(settings.get_cloud_folder()) / backup.CLOUD_SUBDIR))
        head.addWidget(self.cloud_open)
        lay.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(theme.SP_M)
        self.cloud_box = QComboBox()
        self.cloud_now = button("Enviar agora", "secondary", self.t, "fa6s.cloud-arrow-up", "fg")
        row.addWidget(self.cloud_box, 1)
        row.addWidget(self.cloud_now)
        lay.addLayout(row)
        self.cloud_status = QLabel(wordWrap=True)
        self.cloud_status.setProperty("role", "field")
        lay.addWidget(self.cloud_status)
        self.cloud_list = QWidget()               # altura fixa, calculada ao preencher (ver _fit_list)
        self.cloud_rows = QVBoxLayout(self.cloud_list)
        self.cloud_rows.setContentsMargins(0, 0, 0, 0)
        self.cloud_rows.setSpacing(0)
        lay.addWidget(self.cloud_list)
        self._fill_cloud_box()
        self.cloud_box.activated.connect(self._cloud_chosen)
        self.cloud_now.clicked.connect(self._cloud_now)

    def _fill_cloud_box(self):
        current = settings.get_cloud_folder()
        self.cloud_box.blockSignals(True)
        self.cloud_box.clear()
        self.cloud_box.addItem("Desligado", "")
        paths = []
        for label, path in backup.cloud_candidates():
            self.cloud_box.addItem(f"{label} — {path}", str(path))
            paths.append(str(path))
        if current and current not in paths:
            self.cloud_box.addItem(current, current)
        self.cloud_box.addItem("Escolher outra pasta…", "*")
        self.cloud_box.setCurrentIndex(max(0, self.cloud_box.findData(current)))
        self.cloud_box.blockSignals(False)

    def _cloud_chosen(self, _i: int = 0):
        value = self.cloud_box.currentData()
        if value == "*":
            path = QFileDialog.getExistingDirectory(self, "Pasta sincronizada com a nuvem",
                                                    settings.get_cloud_folder() or str(Path.home()))
            if not path:
                self._fill_cloud_box()
                return
            value = path
        settings.set_cloud_folder(value)
        self._fill_cloud_box()
        self.message.emit("Backup na nuvem desligado." if not value else
                          f"Backup na nuvem ligado: {Path(value) / backup.CLOUD_SUBDIR}")
        if value:
            self._cloud_now()
        self._refresh_cloud()

    def _cloud_now(self):
        folder = settings.get_cloud_folder()
        if not folder:
            self.message.emit("Escolha primeiro a pasta da nuvem.")
            return
        try:
            made = backup.cloud_backup(Path(folder))
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Backup na nuvem", f"Não foi possível gravar na pasta da nuvem.\n\n{e}")
            return
        log.info("Backup na nuvem (manual): %s", made)
        self.message.emit(f"Backup enviado para {made.parent}")
        self._refresh_cloud()

    def _refresh_cloud(self):
        if getattr(self, "cloud_box", None) is None:
            return
        folder = settings.get_cloud_folder()
        while self.cloud_rows.count():
            w = self.cloud_rows.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.cloud_now.setEnabled(bool(folder))
        self.cloud_open.setVisible(bool(folder))
        if not folder:
            found = len(backup.cloud_candidates())
            self.cloud_status.setText("Escolha a pasta do OneDrive, Google Drive ou Dropbox deste computador."
                                      + ("" if found else " Não encontrei nenhuma: instale o programa da nuvem "
                                                          "ou escolha a pasta à mão."))
            return
        items = backup.list_cloud(folder)
        self.cloud_status.setText(f"Ao fechar o app, a cópia do dia vai para {Path(folder) / backup.CLOUD_SUBDIR}."
                                  + ("" if items else " Ainda não há cópias lá."))
        for b in items[:5]:
            self.cloud_rows.addWidget(self._local_row(b))
        _fit_list(self.cloud_list)

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
        self._refresh_cloud()
        _fit_list(self.local_box)

    def _local_row(self, b: backup.BackupInfo) -> QFrame:
        row = QFrame(objectName="listRow")
        row.setFixedHeight(theme.ROW_H + 8)          # sem isso o quadro achata as linhas e corta a lista
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 5, 0, 5)
        lay.setSpacing(theme.SP_M)
        when = QLabel(f"{b.modified:%d/%m/%Y %H:%M}")
        when.setFont(theme.mono_font())
        when.setFixedWidth(120)
        kind = ("Nuvem" if b.path.name.startswith(backup.CLOUD_PREFIX) else
                "Antes de restaurar" if b.path.name.startswith(backup.SAFETY_PREFIX) else
                "Antes de atualizar" if b.path.name.startswith(backup.UPDATE_PREFIX) else "Automático")
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
        log.info("Backup manual salvo: %s", dest.name)
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
            safety = backup.restore_from(path)
            log.info("Backup restaurado: %s (cópia dos dados anteriores: %s)", Path(path).name, safety.name)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Restaurar backup", f"Não foi possível restaurar.\n\n{e}")
            return
        QMessageBox.information(self, "Restaurar backup", "Backup restaurado. O IGNF Finora vai reabrir agora.")
        self.restart_requested.emit()

    def _toggle_auto(self, on: bool):
        settings.set_auto_backup(on)
        self.message.emit("Backup automático ligado." if on else "Backup automático desligado.")

    # ---------- fechamento de período ----------
    def _lock_section(self) -> QFrame:
        box, lay = _section("Fechamento de período", "fa6s.lock", self.t)
        lay.addWidget(_muted("Conferiu um mês e está tudo certo? Feche-o: lançamentos até a data escolhida não "
                             "podem mais ser criados, alterados nem excluídos, e a DRE e os relatórios do passado "
                             "ficam como estão. Pagar depois uma conta antiga continua permitido."))
        if not allowed(current_edition(), "period_lock"):
            self.lock_date = None
            lay.addWidget(upgrade_box("Fechamento de período é um recurso das edições Plus e Pro.", self.t, self,
                                      compact=True))
            return box
        self.lock_status = QLabel(wordWrap=True)
        lay.addWidget(self.lock_status)
        row = QHBoxLayout()
        row.setSpacing(theme.SP_M)
        self.lock_date = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.lock_date.setFont(theme.mono_font())
        self.lock_btn = button("Fechar até esta data", "secondary", self.t, "fa6s.lock", "fg")
        self.unlock_btn = button("Reabrir tudo", "link", self.t, "fa6s.lock-open")
        row.addWidget(self.lock_date)
        row.addWidget(self.lock_btn)
        row.addStretch(1)
        row.addWidget(self.unlock_btn)
        lay.addLayout(row)
        self.lock_btn.clicked.connect(self._lock)
        self.unlock_btn.clicked.connect(self._unlock)
        self._refresh_lock()
        return box

    def _refresh_lock(self):
        if getattr(self, "lock_date", None) is None:
            return
        with Session() as s:
            lock = period_lock.locked_through(s, self.profile.id)
        today = date.today()
        last_month_end = today.replace(day=1) - timedelta(days=1)
        self.lock_date.setMaximumDate(QDate(today.year, today.month, today.day))
        self.lock_date.setDate(QDate(last_month_end.year, last_month_end.month, last_month_end.day))
        if lock:
            self.lock_status.setText(f"Fechado até {lock:%d/%m/%Y}.")
            set_tone(self.lock_status, None)
        else:
            self.lock_status.setText("Nenhum período fechado: todos os lançamentos podem ser alterados.")
            set_tone(self.lock_status, "mut")
        self.unlock_btn.setVisible(lock is not None)

    def _lock(self):
        day = self.lock_date.date().toPython()
        if QMessageBox.question(self, "Fechar período",
                                f"Fechar tudo até {day:%d/%m/%Y}? Dá para reabrir depois, se precisar.") \
                != QMessageBox.Yes:
            return
        try:
            with Session() as s:
                period_lock.set_lock(s, self.profile.id, day)
        except ValueError as e:
            QMessageBox.warning(self, "Fechar período", str(e))
            return
        log.info("Período fechado até %s", day)
        self.message.emit(f"Período fechado até {day:%d/%m/%Y}.")
        self._refresh_lock()

    def _unlock(self):
        with Session() as s:
            period_lock.set_lock(s, self.profile.id, None)
        log.info("Período reaberto")
        self.message.emit("Período reaberto: todos os lançamentos podem ser alterados.")
        self._refresh_lock()

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
        self.tabs_icons = QCheckBox("Abas no topo só com ícones (o nome aparece ao passar o mouse)")
        self.tabs_icons.setChecked(settings.get_tabs_icons())
        self.tabs_icons.toggled.connect(self._tabs_icons)
        lay.addWidget(self.tabs_icons)
        lay.addWidget(_muted("Dica: o botão « ao lado de \"Tema\" recolhe e expande o menu a qualquer momento."))
        return box

    def _tabs_icons(self, on: bool):
        settings.set_tabs_icons(on)
        w = self.window()
        if hasattr(w, "tabs"):
            w.tabs.set_icons_only(on)

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
            log.info("Ativação de licença recusada: %s", e)
            self._key_err(str(e))
            return
        self._key_err(None)
        log.info("Licença ativada: edição %s, nº %s", lic.edition, lic.license_id)
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
        log.info("Licença removida deste computador")
        self.restart_requested.emit()

    # ---------- sobre ----------
    def _about_section(self) -> QFrame:
        box, lay = _section("Sobre", "fa6s.circle-info", self.t)
        lay.addWidget(QLabel(f"IGNF Finora · versão {__version__}", objectName="cardTitle"))
        from finora.core import vendor
        dev = QLabel(
            f"Desenvolvido por <b>{vendor.COMPANY}</b> · CNPJ {vendor.CNPJ}<br>"
            f"{vendor.ADDRESS}<br>"
            f'E-mail: <a href="mailto:{vendor.EMAIL}">{vendor.EMAIL}</a> &nbsp;·&nbsp; '
            f'Telefone / WhatsApp: <a href="{vendor.WHATSAPP}">{vendor.PHONE}</a><br>'
            f'<a href="{vendor.CONTACT_PAGE}">Suporte e contato</a> &nbsp;·&nbsp; '
            f'<a href="{vendor.LAB_PAGE}">IGNF LAB (software)</a> &nbsp;·&nbsp; <a href="{vendor.SITE}">ignf.com.br</a>',
            wordWrap=True, openExternalLinks=True)
        dev.setTextFormat(Qt.RichText)
        dev.setProperty("role", "muted")
        lay.addWidget(dev)
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
        upd = QHBoxLayout()
        self.update_chk = QCheckBox("Avisar quando houver versão nova (consulta o GitHub uma vez por dia)")
        self.update_chk.setChecked(settings.get_update_check())
        self.update_chk.toggled.connect(settings.set_update_check)
        self.update_now = button("Verificar agora", "link", self.t, "fa6s.rotate")
        self.update_now.clicked.connect(self._check_update)
        upd.addWidget(self.update_chk, 1)
        upd.addWidget(self.update_now)
        lay.addLayout(upd)
        terms = button("Termos de uso e privacidade", "link", self.t, "fa6s.file-contract")
        terms.clicked.connect(self._show_terms)
        lay.addWidget(terms, 0, Qt.AlignLeft)
        return box

    def _show_terms(self):
        from finora.ui.terms_dialog import TermsDialog
        TermsDialog(self).exec()

    def _check_update(self):
        from finora.ui.update_check import UpdateChecker
        self._checker = UpdateChecker(self)
        self._checker.done.connect(self.message.emit)
        self._checker.found.connect(lambda rel: self.window().show_update(rel)
                                    if hasattr(self.window(), "show_update") else None)
        self.message.emit("Consultando…")
        self._checker.start()

    def set_admin(self, is_admin: bool):
        """Sem acesso de administração: só Aparência e Sobre."""
        for w in self.admin_sections:
            w.setVisible(is_admin)

    # ---------- página ----------
    def refresh(self):
        self._refresh_backup()
        self.currencies.refresh()      # contas novas em outra moeda aparecem aqui
        self.data_location.refresh()
        self._refresh_lock()

    def apply_theme(self, t: dict):
        self.t = t
