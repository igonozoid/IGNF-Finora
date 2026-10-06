import sys
from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from finora.core import logs, paths, settings
from finora.core.db import Session, init_db
from finora.services import backup, setup
from finora.ui import fonts, locale_br, theme
from finora.ui.error_dialog import show_error
from finora.ui.first_run import FirstRunWizard
from finora.ui.main_window import MainWindow

log = logs.log


def main():
    logs.setup()
    logs.session_start(paths.DATA_DIR)
    moved = settings.migrate_from_registry()   # versões antigas guardavam as preferências no Registro
    if moved:
        log.info("Preferências trazidas do Registro do Windows: %d", moved)

    app = QApplication(sys.argv)
    qInstallMessageHandler(logs.qt_message_handler)
    if not locale_br.install(app):
        log.warning("Tradução pt-BR do Qt não encontrada; botões padrão ficarão em inglês")
    logs.set_error_handler(show_error)
    app.setOrganizationName(settings.ORG)
    app.setApplicationName(settings.APP)
    app.setStyle("Fusion")
    loaded = fonts.load()
    if not {"IBM Plex Sans", "IBM Plex Mono"} <= loaded:
        log.warning("Fontes IBM Plex não carregadas (%s); usando as do sistema", ", ".join(sorted(loaded)) or "nenhuma")
    font = QFont()
    font.setFamilies(theme.FONT_UI)
    font.setPointSize(theme.FONT_PT)
    app.setFont(font)
    t = theme.apply(app, settings.get_theme(theme.DEFAULT_THEME))
    if paths.DATA_NOTICE:
        log.warning(paths.DATA_NOTICE.replace("\n", " "))
        QMessageBox.information(None, "Onde ficam seus dados", paths.DATA_NOTICE)

    try:
        safety = init_db()
    except Exception:
        log.exception("Não foi possível abrir ou atualizar o banco")
        QMessageBox.critical(None, "Não foi possível abrir seus dados",
                             "O IGNF Finora não conseguiu abrir o arquivo de dados.\n\n"
                             f"Os detalhes foram salvos em {logs.LOG_FILE}.\n"
                             "Seus backups ficam em data\\backups.")
        return 1
    if safety:
        log.info("Banco atualizado; cópia de antes da atualização em %s", safety)

    with Session() as s:
        profile = setup.current_profile(s)
    if profile is None:
        wizard = FirstRunWizard(t)
        if wizard.exec() != QDialog.Accepted:
            return 0  # fechou sem concluir: o assistente volta na próxima abertura
        profile = wizard.profile
        log.info("Primeiro uso concluído")

    if settings.get_auto_backup():
        try:
            made = backup.auto_backup()    # 1 por dia, mantém os últimos 7 em data/backups
            if made:
                log.info("Backup automático: %s", made.name)
        except Exception:                  # backup nunca impede o app de abrir
            log.exception("Backup automático falhou")

    w = MainWindow(profile); w.show()
    code = app.exec()
    log.info("App fechado")
    return code


if __name__ == "__main__":
    sys.exit(main())
