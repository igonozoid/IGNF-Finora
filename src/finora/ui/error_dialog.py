"""Janela amigável para erros inesperados (o detalhe técnico fica no log)."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from finora.core import logs


def show_error(summary: str, details: str) -> None:
    app = QApplication.instance()
    if app is None:
        return
    box = QMessageBox(app.activeWindow())
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Algo deu errado")
    box.setText("O IGNF Finora encontrou um problema inesperado.")
    box.setInformativeText(
        "O que já estava salvo continua salvo. Se a última ação não terminou, tente de novo.\n\n"
        "Se o problema se repetir, envie o arquivo finora.log (da pasta de dados) para o suporte.")
    box.setDetailedText(details)
    copy = box.addButton("Copiar detalhes", QMessageBox.ActionRole)
    folder = box.addButton("Abrir pasta do log", QMessageBox.ActionRole)
    box.addButton("Continuar", QMessageBox.AcceptRole)
    box.exec()
    if box.clickedButton() is copy:
        QGuiApplication.clipboard().setText(f"{summary}\n\n{details}")
    elif box.clickedButton() is folder:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs.LOG_FILE.parent)))
