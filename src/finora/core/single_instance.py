"""Um Finora por pasta de dados: abrir de novo só traz a janela que já está aberta (mesmo escondida na bandeja).

O primeiro a abrir escuta num "canal local" (QLocalServer) com nome tirado da pasta de dados; os seguintes se
conectam, pedem para mostrar a janela e saem. Pastas diferentes (outra instalação, testes) não se misturam.
"""
import hashlib
import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

_server: QLocalServer | None = None
window = None                      # a janela principal da sessão atual (run_session atualiza)


def name_for(data_dir) -> str:
    return "ignf-finora-" + hashlib.sha1(str(data_dir).lower().encode()).hexdigest()[:16]


def allow_foreground() -> None:
    """Windows só deixa um programa vir para a frente se quem está na frente permitir. Quem o usuário acabou de abrir
    (este) está na frente: libera para o Finora que já estava aberto, senão a janela dele fica atrás e parece que o
    app só roda "em segundo plano"."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)      # ASFW_ANY
    except (AttributeError, OSError):
        pass


def already_running(name: str) -> bool:
    """True se outro Finora já usa essa pasta (e ele foi avisado para aparecer)."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(500):
        return False
    allow_foreground()
    sock.write(b"show")
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def listen(name: str) -> None:
    global _server
    QLocalServer.removeServer(name)        # sobra de um Finora que fechou de mau jeito
    _server = QLocalServer()
    _server.newConnection.connect(_on_connection)
    _server.listen(name)


def stop() -> None:
    global _server
    if _server is not None:
        _server.close()
        _server = None


def _on_connection():
    while _server is not None and _server.hasPendingConnections():
        sock = _server.nextPendingConnection()
        sock.disconnected.connect(sock.deleteLater)
    bring_to_front()


def bring_to_front() -> None:
    w = QApplication.activeModalWidget() or window
    if w is None:
        return
    if w.isMinimized() or w.isHidden():
        w.showNormal()
    w.raise_()
    w.activateWindow()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(int(w.winId()))
        except (AttributeError, OSError):
            pass
    QApplication.alert(w)                  # se o Windows ainda assim não deixar: o botão pisca na barra de tarefas
