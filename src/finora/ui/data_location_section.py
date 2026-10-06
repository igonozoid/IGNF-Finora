"""Configurações › Onde ficam os dados: neste computador, num servidor da rede, ou este PC é o servidor."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressDialog,
    QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from finora.core import db, settings
from finora.core.licensing import allowed, current_edition
from finora.core.logs import log
from finora.server import mariadb
from finora.services import dbcopy
from finora.ui import theme
from finora.ui.widgets import WrapFrame, button, field_label, icon_label, set_tone, upgrade_box

LOCK_MSG = ("Usar o Finora em vários computadores da rede (com um deles como servidor) é um recurso das "
            "edições Plus e Pro.")
MODES = list(settings.DB_MODES)


def _muted(text: str) -> QLabel:
    lbl = QLabel(text, wordWrap=True)
    lbl.setProperty("role", "muted")
    return lbl


class _Busy:
    def __enter__(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)

    def __exit__(self, *_exc):
        QApplication.restoreOverrideCursor()


class DataLocationSection(QFrame):
    message = Signal(str)
    restart_requested = Signal()

    def __init__(self, t: dict, max_w: int):
        super().__init__(objectName="card")
        self.t = t
        self.setMaximumWidth(max_w)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, theme.SP_L, 14, 14)
        lay.setSpacing(theme.SP_M)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(icon_label("fa6s.network-wired", t, "acc", 12))
        head.addWidget(QLabel("Onde ficam os dados", objectName="sectionTitle"))
        head.addStretch(1)
        lay.addLayout(head)
        self.now = QLabel(wordWrap=True)
        lay.addWidget(self.now)
        self.cfg = settings.get_db_config()
        self.locked = not allowed(current_edition(), "network")
        if self.locked:
            lay.addWidget(_muted("Seus dados ficam neste computador."))
            lay.addWidget(upgrade_box(LOCK_MSG, t, self, compact=True))
            self._show_now()
            return

        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.mode_group = QButtonGroup(self, exclusive=True)
        for i, (k, label) in enumerate(settings.DB_MODES.items()):
            b = QPushButton(label, checkable=True)
            b.setProperty("variant", "seg")
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(MODES) - 1 else "mid")
            self.mode_group.addButton(b, i)
            seg.addWidget(b, 1)
        lay.addLayout(seg)
        self.pages = QStackedWidget(objectName="formPages")
        self.pages.addWidget(self._local_page())
        self.pages.addWidget(self._client_page())
        self.pages.addWidget(self._server_page())
        lay.addWidget(self.pages)
        self.mode_group.idClicked.connect(self._mode_clicked)
        self.mode_group.button(MODES.index(self.cfg.mode)).setChecked(True)
        self.pages.setCurrentIndex(MODES.index(self.cfg.mode))
        self.refresh()

    # ---------- páginas ----------
    def _local_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(_muted("Os dados ficam só neste computador, no arquivo data/finora.db. É o jeito mais "
                             "simples para quem usa o Finora num computador só."))
        self.bring_back = QCheckBox("Trazer os dados do servidor para este computador (substitui os daqui)")
        self.back_btn = button("Voltar a usar os dados deste computador", "secondary")
        lay.addWidget(self.bring_back)
        lay.addWidget(self.back_btn, 0, Qt.AlignLeft)
        self.back_btn.clicked.connect(self._use_local)
        return w

    def _client_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(_muted("Outro computador da rede é o Finora Servidor. Copie aqui o endereço e a senha que "
                             "aparecem nele (Configurações › Onde ficam os dados)."))
        row = QHBoxLayout()
        row.setSpacing(theme.SP_M)
        self.host = QLineEdit(placeholderText="Ex.: 192.168.0.10")
        self.port = QSpinBox(minimum=1, maximum=65535, value=mariadb.DEFAULT_PORT)
        self.port.setFont(theme.mono_font())
        self.password = QLineEdit(echoMode=QLineEdit.Password, placeholderText="abcd-efgh-jkmn")
        for label, wid, stretch in (("Endereço do servidor", self.host, 2), ("Porta", self.port, 0),
                                    ("Senha", self.password, 2)):
            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(field_label(label, self.t))
            col.addWidget(wid)
            row.addLayout(col, stretch)
        lay.addLayout(row)
        self.client_status = QLabel(wordWrap=True)
        lay.addWidget(self.client_status)
        btns = QHBoxLayout()
        self.test_btn = button("Testar conexão", "secondary")
        self.connect_btn = button("Usar este servidor", "primary")
        btns.addWidget(self.test_btn)
        btns.addWidget(self.connect_btn)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.test_btn.clicked.connect(self._test)
        self.connect_btn.clicked.connect(self._use_client)
        return w

    def _server_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(_muted("Este computador guarda os dados (num banco MariaDB que o Finora baixa e cuida "
                             "sozinho) e os outros PCs da rede usam o Finora conectados nele. Deixe este "
                             "computador ligado enquanto os outros usam."))
        self.server_status = QLabel(wordWrap=True)
        lay.addWidget(self.server_status)
        self.info = WrapFrame(objectName="lockBox")
        il = QVBoxLayout(self.info)
        il.setContentsMargins(theme.SP_M, theme.SP_M, theme.SP_M, theme.SP_M)
        il.setSpacing(4)
        self.info_text = QLabel(wordWrap=True, textInteractionFlags=Qt.TextSelectableByMouse)
        self.info_text.setTextFormat(Qt.RichText)
        il.addWidget(self.info_text)
        copy = button("Copiar endereço e senha", "link", self.t, "fa6s.copy")
        copy.clicked.connect(self._copy_info)
        il.addWidget(copy, 0, Qt.AlignLeft)
        lay.addWidget(self.info)
        self.firewall = _muted(mariadb.env_has_firewall_hint())
        lay.addWidget(self.firewall)
        self.take_data = QCheckBox("Levar os dados deste computador para o servidor")
        self.take_data.setChecked(True)
        lay.addWidget(self.take_data)
        btns = QHBoxLayout()
        self.download_btn = button("Baixar o MariaDB (cerca de 95 MB)", "secondary", self.t, "fa6s.download", "fg")
        self.start_btn = button("Ligar o servidor", "primary")
        self.stop_btn = button("Desligar", "secondary")
        btns.addWidget(self.download_btn)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.download_btn.clicked.connect(self._download)
        self.start_btn.clicked.connect(self._start_server)
        self.stop_btn.clicked.connect(self._stop_server)
        return w

    # ---------- estado ----------
    def _show_now(self):
        self.now.setText(("Agora: " + db.describe()) if not db.is_server() else
                         f"<b>Agora:</b> {db.describe()} (conectado)")
        self.now.setTextFormat(Qt.RichText)

    def refresh(self):
        self.cfg = settings.get_db_config()
        self._show_now()
        if self.locked:
            return
        on_server = db.is_server()
        self.bring_back.setVisible(on_server)
        self.back_btn.setVisible(self.cfg.mode != "local")
        self.host.setText(self.cfg.host)
        self.port.setValue(self.cfg.port)
        self.password.setText(self.cfg.password if self.cfg.mode == "client" else "")
        lay = mariadb.layout()
        have = mariadb.installed(lay)
        running = mariadb.is_listening(self.cfg.port)
        is_server_mode = self.cfg.mode == "server"
        self.download_btn.setVisible(not have)
        self.start_btn.setVisible(have and not (is_server_mode and running))
        self.start_btn.setText("Ligar o servidor" if is_server_mode else "Tornar este computador o servidor")
        self.stop_btn.setVisible(is_server_mode and running)
        self.take_data.setVisible(have and not is_server_mode)
        self.firewall.setVisible(is_server_mode or have)
        if not have:
            self.server_status.setText("1º passo: baixar o MariaDB (o banco usado pelo servidor), do site oficial.")
            set_tone(self.server_status, None)
        elif not is_server_mode:
            self.server_status.setText("Pronto para virar o servidor.")
            set_tone(self.server_status, None)
        else:
            self.server_status.setText("Servidor ligado." if running else "Servidor desligado: os outros PCs "
                                                                          "não conseguem usar o Finora.")
            set_tone(self.server_status, "pos" if running else "neg")
        if is_server_mode:
            ips = mariadb.lan_addresses()
            self._info = (f"Endereço: {ips[0]}\nPorta: {self.cfg.port}\nSenha: {self.cfg.password}")
            self.info_text.setText("Nos outros computadores, escolha <b>Num servidor da rede</b> e informe:<br>"
                                   f"Endereço: <b>{' ou '.join(ips)}</b> &nbsp;·&nbsp; Porta: <b>{self.cfg.port}</b>"
                                   f" &nbsp;·&nbsp; Senha: <b>{self.cfg.password}</b>")
        self.info.setVisible(is_server_mode)

    def _mode_clicked(self, i: int):
        self.pages.setCurrentIndex(i)

    # ---------- ações ----------
    def _ask_restart(self, msg: str):
        QMessageBox.information(self, "Onde ficam os dados", msg + "\n\nO IGNF Finora vai reabrir agora.")
        self.restart_requested.emit()

    def _use_local(self):
        if self.bring_back.isChecked() and db.is_server():
            if QMessageBox.question(self, "Trazer os dados", "Os dados deste computador serão substituídos pelos "
                                                             "do servidor. Continuar?") != QMessageBox.Yes:
                return
            from finora.services import backup
            safety = backup.backup_to(db.BACKUP_DIR / "antes-de-trazer-do-servidor.db", db.DB_FILE)
            with _Busy():
                dbcopy.copy_all(db.engine, db.make_engine(f"sqlite:///{db.DB_FILE}"))
            log.info("Dados trazidos do servidor (cópia dos anteriores em %s)", safety)
        cfg = settings.get_db_config()
        cfg.mode = "local"
        settings.set_db_config(cfg)
        self._ask_restart("Pronto: o Finora volta a usar os dados deste computador.")

    def _test(self) -> bool:
        try:
            with _Busy():
                mariadb.check_connection(self.host.text().strip(), self.port.value(), self.password.text())
        except mariadb.ServerError as e:
            self.client_status.setText(str(e))
            set_tone(self.client_status, "neg")
            return False
        self.client_status.setText("Conectou! O servidor está respondendo.")
        set_tone(self.client_status, "pos")
        return True

    def _use_client(self):
        if not self.host.text().strip():
            self.client_status.setText("Informe o endereço do servidor.")
            set_tone(self.client_status, "neg")
            return
        if not self._test():
            return
        cfg = settings.DbConfig("client", self.host.text().strip(), self.port.value(), mariadb.DB_NAME,
                                mariadb.DB_USER, self.password.text())
        server = db.make_engine(cfg.url())
        try:
            empty = not dbcopy.has_data(server)
            if empty and not db.is_server() and dbcopy.has_data(db.engine):
                ans = QMessageBox.question(self, "Servidor vazio", "O servidor ainda não tem dados. Levar os dados "
                                                                   "deste computador para ele?")
                if ans == QMessageBox.Yes:
                    with _Busy():
                        dbcopy.copy_all(db.engine, server)
        finally:
            server.dispose()
        settings.set_db_config(cfg)
        log.info("Modo cliente: servidor %s:%s", cfg.host, cfg.port)
        self._ask_restart(f"Pronto: este computador passa a usar o servidor {cfg.host}.")

    def _download(self):
        dlg = QProgressDialog("Baixando o MariaDB do site oficial…", "Cancelar", 0, 100, self)
        dlg.setWindowTitle("Finora Servidor")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)

        def progress(done, total):
            if total:
                dlg.setValue(int(done * 100 / total))
            QApplication.processEvents()
            if dlg.wasCanceled():
                raise mariadb.ServerError("Download cancelado.")

        try:
            mariadb.download(progress=progress)
        except mariadb.ServerError as e:
            dlg.close()
            QMessageBox.warning(self, "Finora Servidor", str(e))
            return
        dlg.close()
        self.message.emit("MariaDB baixado e conferido.")
        self.refresh()

    def _start_server(self):
        lay = mariadb.layout()
        cfg = settings.get_db_config()
        first_time = cfg.mode != "server"
        root = settings.get_server_root() or mariadb.new_password() + mariadb.new_password()
        app_pw = cfg.password if cfg.mode == "server" and cfg.password else mariadb.new_password()
        port = cfg.port if cfg.mode == "server" else mariadb.DEFAULT_PORT
        try:
            with _Busy():
                settings.set_server_root(root)
                mariadb.initialize(lay, root, port)
                mariadb.start(lay, port)
                mariadb.wait_ready(port, "root", root, timeout=40)
                mariadb.setup_database(port, root, app_pw)
                new = settings.DbConfig("server", "", port, mariadb.DB_NAME, mariadb.DB_USER, app_pw)
                if first_time and self.take_data.isChecked() and not db.is_server():
                    server = db.make_engine(new.url())
                    try:
                        if dbcopy.has_data(server):
                            raise mariadb.ServerError("O banco do servidor já tem dados; não copiei nada por cima.")
                        dbcopy.copy_all(db.engine, server)
                    finally:
                        server.dispose()
        except mariadb.ServerError as e:
            QMessageBox.warning(self, "Finora Servidor", str(e))
            self.refresh()
            return
        settings.set_db_config(new)
        log.info("Este PC virou o Finora Servidor (porta %s)", port)
        if first_time:
            self._ask_restart("O servidor está ligado. Anote o endereço e a senha que vão aparecer aqui para "
                              "configurar os outros computadores.")
        else:
            self.message.emit("Servidor ligado.")
            self.refresh()

    def _stop_server(self):
        if QMessageBox.question(self, "Desligar o servidor", "Os outros computadores param de acessar o Finora "
                                                             "até você ligar de novo. Desligar?") != QMessageBox.Yes:
            return
        try:
            with _Busy():
                db.engine.dispose()
                mariadb.stop(mariadb.layout(), self.cfg.port, settings.get_server_root())
        except mariadb.ServerError as e:
            QMessageBox.warning(self, "Finora Servidor", str(e))
            return
        QMessageBox.information(self, "Finora Servidor", "Servidor desligado. O Finora deste computador também "
                                                         "fecha agora (os dados estão no servidor). Ao abrir de "
                                                         "novo, o servidor liga sozinho.")
        QApplication.instance().quit()

    def _copy_info(self):
        QGuiApplication.clipboard().setText(getattr(self, "_info", ""))
        self.message.emit("Endereço e senha copiados.")

    def apply_theme(self, t: dict):
        self.t = t

