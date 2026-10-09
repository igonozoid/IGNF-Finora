import sys
from pathlib import Path
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


def smoke_test() -> int:
    """`IGNF-Finora --teste`: confere o pacote sem mostrar nada (fontes, tradução, banco, migrações e a janela
    principal) e sai. Use com FINORA_DATA_DIR apontando para uma pasta vazia."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from finora import __version__
    from finora.core import db
    app = QApplication(sys.argv)
    problems = []
    if not {"IBM Plex Sans", "IBM Plex Mono"} <= fonts.load():
        problems.append("fontes IBM Plex")
    if not locale_br.install(app):
        problems.append("tradução pt-BR do Qt")
    theme.apply(app, "light")
    init_db()
    current, head, _ = db.schema_state()
    if current != head:
        problems.append(f"migrações ({current} != {head})")
    with Session() as s:
        profile = setup.current_profile(s) or setup.run_first_setup(
            s, name="Teste", currency="BRL", account_name="Banco", account_kind="bank", balance=0)
    w = MainWindow(profile)
    for key in ("dashboard", "entries", "reports", "settings"):
        w.go_to(key)
    import tempfile
    from pathlib import Path
    from finora.services import reconcile
    from finora.ui import exporting
    with tempfile.TemporaryDirectory() as tmp:            # exportar PDF e Excel (impressão e openpyxl no pacote)
        sheet = w.page("reports").views["dre"].export_sheet()
        exporting.save(sheet, "pdf", str(Path(tmp) / "t.pdf"))
        exporting.save(sheet, "xlsx", str(Path(tmp) / "t.xlsx"))
        if not (Path(tmp) / "t.pdf").read_bytes().startswith(b"%PDF"):
            problems.append("exportar PDF")
    ofx = (b"OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n\n<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>BRL"
           b"<BANKACCTFROM><BANKID>1<ACCTID>1<ACCTTYPE>CHECKING</BANKACCTFROM><BANKTRANLIST><DTSTART>20260101"
           b"<DTEND>20260102<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260101<TRNAMT>-1.00<FITID>1<MEMO>X</STMTTRN>"
           b"</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>")
    if len(reconcile.parse_ofx(ofx)) != 1:                # ler extrato (ofxparse + BeautifulSoup no pacote)
        problems.append("ler OFX")
    QTimer.singleShot(300, app.quit)
    app.exec()
    print(f"IGNF Finora {__version__}: " + ("OK" if not problems else "PROBLEMAS: " + ", ".join(problems)))
    return 1 if problems else 0


def main():
    if "--teste" in sys.argv:
        return smoke_test()
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

    from finora.ui.terms_dialog import TERMS_VERSION, TermsDialog
    if settings.get_terms_accepted() != TERMS_VERSION:
        if TermsDialog(ask=True).exec() != QDialog.Accepted:
            return 0
        settings.set_terms_accepted(TERMS_VERSION)
        log.info("Termos de uso aceitos (versão %s)", TERMS_VERSION)
    from finora.ui.connection import connect_from_settings
    if not connect_from_settings():
        return 0
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
        from finora.services import currencies
        currencies.load(s)                  # moedas cadastradas entram nas listas
        profile = setup.current_profile(s)
    if profile is None:
        wizard = FirstRunWizard(t)
        if wizard.exec() != QDialog.Accepted:
            return 0  # fechou sem concluir: o assistente volta na próxima abertura
        profile = wizard.profile
        log.info("Primeiro uso concluído")

    if settings.get_auto_backup() and settings.get_db_config().mode != "client":   # no servidor, ele faz
        try:
            made = backup.auto_backup()    # 1 por dia, mantém os últimos 7 em data/backups
            if made:
                log.info("Backup automático: %s", made.name)
        except Exception:                  # backup nunca impede o app de abrir
            log.exception("Backup automático falhou")

    code = run_session(app, t, first_profile=profile)
    cloud_backup_on_close()
    log.info("App fechado")
    return code


def run_session(app, t: dict, first_profile=None) -> int:
    """Login (se precisar) → entidade → janela. "Trocar de usuário/entidade" fecha a janela e volta aqui."""
    from finora.core import current
    from finora.ui.session_flow import pick_entity, pick_user
    action, user, profile, code = "user", None, first_profile, 0
    while True:
        if action == "user":
            current.clear()
            user = pick_user(t)
            if user is None:
                return code                      # fechou o login: sai do app
        chosen = pick_entity(user, t, ask=action == "entity")
        if chosen is None and (action != "entity" or profile is None):
            if action == "user":
                QMessageBox.warning(None, "IGNF Finora", "Seu usuário não tem nenhuma entidade liberada. "
                                                         "Peça acesso a um administrador.")
            return code
        profile = chosen or profile               # cancelou a troca de entidade: continua na mesma
        log.info("Abrindo %s como %s", profile.name, user.name if user else "-")
        w = MainWindow(profile, user)
        w.show()
        from finora.ui.update_check import check_in_background
        check_in_background(w)
        code = app.exec()
        if not w.next_action:
            return code
        action = w.next_action


def cloud_backup_on_close() -> None:
    """Edições pagas: ao fechar, a cópia do dia vai para a pasta da nuvem escolhida em Configurações."""
    from finora.core.licensing import allowed, current_edition
    folder = settings.get_cloud_folder()
    if not folder or not allowed(current_edition(), "cloud_backup"):
        return
    try:
        made = backup.cloud_backup(Path(folder))
        log.info("Backup na nuvem: %s", made)
    except Exception:                      # nunca impede o app de fechar
        log.exception("Backup na nuvem falhou")


if __name__ == "__main__":
    sys.exit(main())
