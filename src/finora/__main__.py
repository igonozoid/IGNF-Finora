import sys
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from finora.core import settings
from finora.core.db import init_db
from finora.ui import theme
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
    w = MainWindow(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
