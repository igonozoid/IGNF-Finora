import sys
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog
from finora.core import settings
from finora.core.db import Session, init_db
from finora.services import setup
from finora.ui import theme
from finora.ui.first_run import FirstRunWizard
from finora.ui.main_window import MainWindow

def main():
    init_db()
    app = QApplication(sys.argv)
    app.setOrganizationName(settings.ORG)
    app.setApplicationName(settings.APP)
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(theme.FONT_UI)
    font.setPointSize(theme.FONT_PT)
    app.setFont(font)
    t = theme.apply(app, settings.get_theme(theme.DEFAULT_THEME))

    with Session() as s:
        profile = setup.current_profile(s)
    if profile is None:
        wizard = FirstRunWizard(t)
        if wizard.exec() != QDialog.Accepted:
            return  # fechou sem concluir: o assistente volta na próxima abertura
        profile = wizard.profile

    w = MainWindow(profile); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
