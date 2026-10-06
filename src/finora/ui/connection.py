"""Abrir o app no banco certo: este PC (SQLite) ou o Finora Servidor da rede (MariaDB)."""
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from finora.core import db, settings
from finora.core.licensing import allowed, current_edition
from finora.core.logs import log
from finora.server import mariadb


def connect_from_settings(parent=None) -> bool:
    """Aponta o app para o banco configurado. Devolve False se o usuário preferiu sair."""
    cfg = settings.get_db_config()
    if cfg.mode == "local":
        return True
    if not allowed(current_edition(), "network"):
        log.warning("Modo rede configurado, mas a edição não permite; usando os dados deste PC")
        QMessageBox.information(parent, "IGNF Finora", "O uso em rede faz parte das edições Plus e Pro. "
                                                       "Abrindo os dados deste computador.")
        return True
    while True:
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                if cfg.mode == "server":
                    ensure_local_server(cfg)
                mariadb.check_connection("127.0.0.1" if cfg.mode == "server" else cfg.host, cfg.port, cfg.password)
            finally:
                QApplication.restoreOverrideCursor()
            db.use(cfg.url())
            log.info("Conectado ao servidor %s:%s", cfg.host or "127.0.0.1", cfg.port)
            return True
        except mariadb.ServerError as e:
            log.warning("Sem conexão com o servidor: %s", e)
            box = QMessageBox(QMessageBox.Warning, "Servidor do Finora", "Não consegui conectar ao servidor.",
                              parent=parent)
            box.setInformativeText(str(e))
            retry = box.addButton("Tentar de novo", QMessageBox.AcceptRole)
            local = box.addButton("Usar os dados deste computador", QMessageBox.ActionRole)
            box.addButton("Sair", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is retry:
                continue
            if box.clickedButton() is local:
                return True                       # só nesta abertura; a configuração continua a mesma
            return False


def ensure_local_server(cfg: settings.DbConfig) -> None:
    """Este PC é o servidor: liga o MariaDB se ele estiver parado."""
    lay = mariadb.layout()
    if mariadb.is_listening(cfg.port):
        return
    if not mariadb.installed(lay):
        raise mariadb.ServerError("Os programas do servidor não estão nesta pasta. Em Configurações › Onde ficam "
                                  "os dados, prepare o servidor de novo.")
    mariadb.start(lay, cfg.port)
    mariadb.wait_ready(cfg.port, mariadb.DB_USER, cfg.password, timeout=40)
