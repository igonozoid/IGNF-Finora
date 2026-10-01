import sys
from PySide6.QtWidgets import QApplication
from finora.core.db import init_db
from finora.ui.main_window import MainWindow

def main():
    init_db()
    app = QApplication(sys.argv)
    app.setApplicationName("IGNF Finora")
    w = MainWindow(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
