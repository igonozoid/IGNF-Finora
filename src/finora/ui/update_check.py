"""Consulta de versão nova em segundo plano (QNetworkAccessManager: não trava a abertura do app)."""
import json
from datetime import date

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from finora import __version__
from finora.core import settings
from finora.core.logs import log
from finora.services import updates


class UpdateChecker(QObject):
    found = Signal(object)          # updates.Release
    done = Signal(str)              # mensagem (para "Verificar agora")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self.reply: QNetworkReply | None = None

    def start(self):
        req = QNetworkRequest(QUrl(updates.API_URL))
        req.setRawHeader(b"User-Agent", f"IGNF-Finora/{__version__}".encode())
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        req.setTransferTimeout(8000)
        self.reply = self.nam.get(req)
        self.reply.finished.connect(self._finished)

    def _finished(self):
        reply, self.reply = self.reply, None
        reply.deleteLater()
        if reply.error() != QNetworkReply.NoError:
            log.info("Consulta de versão nova falhou: %s", reply.errorString())
            self.done.emit("Não consegui consultar agora (sem internet?).")
            return
        settings.set_update_last(date.today().isoformat())
        try:
            rel = updates.parse_release(json.loads(bytes(reply.readAll()).decode("utf-8")))
        except ValueError:
            rel = None
        if rel and updates.is_newer(rel.version, __version__):
            log.info("Versão nova disponível: %s", rel.version)
            self.found.emit(rel)
            self.done.emit(f"Versão {rel.version} disponível.")
        else:
            self.done.emit(f"Você está com a versão mais nova ({__version__}).")


def check_in_background(window) -> None:
    """Na abertura: no máximo uma vez por dia, se o usuário não desligou."""
    if not settings.get_update_check() or not updates.due(settings.get_update_last()):
        return
    window._update_checker = UpdateChecker(window)
    window._update_checker.found.connect(window.show_update)
    window._update_checker.start()
