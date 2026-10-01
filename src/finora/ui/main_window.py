from PySide6.QtWidgets import QMainWindow, QLabel
import qtawesome as qta

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IGNF Finora")
        self.setWindowIcon(qta.icon("fa5s.coins", color="#e09a0a"))
        self.resize(1366, 800)
        self.setCentralWidget(QLabel("IGNF Finora — em construção"))
