"""Log em arquivo (data/finora.log) e captura de erros inesperados.

Nada de dado sensível no log: sem chave de licença, sem valores de lançamentos.
"""
import logging
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from finora import __version__
from finora.core.paths import DATA_DIR

LOG_FILE = DATA_DIR / "finora.log"
MAX_BYTES = 1_000_000
BACKUPS = 3

log = logging.getLogger("finora")
_on_error = None          # função da interface que mostra a janela "algo deu errado"
_handling = threading.local()


def setup(log_file: Path | None = None, level: int = logging.INFO) -> Path:
    """Liga o log em arquivo (com rotação) e os ganchos de erro. Pode ser chamado de novo (testes)."""
    path = Path(log_file or LOG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                                           "%Y-%m-%d %H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False
    sys.excepthook = _excepthook
    threading.excepthook = lambda args: _excepthook(args.exc_type, args.exc_value, args.exc_traceback)
    return path


def session_start(data_dir: Path) -> None:
    log.info("---- IGNF Finora %s · Python %s · %s %s · dados em %s", __version__, platform.python_version(),
             platform.system(), platform.release(), data_dir)


def set_error_handler(fn) -> None:
    """A interface registra aqui a janela amigável; ela recebe (mensagem curta, detalhes)."""
    global _on_error
    _on_error = fn


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    log.critical("Erro inesperado:\n%s", details)
    if _on_error is None or getattr(_handling, "busy", False):
        sys.__excepthook__(exc_type, exc, tb)
        return
    _handling.busy = True          # um erro dentro da própria janela de erro não abre outra janela
    try:
        _on_error(f"{exc_type.__name__}: {exc}", details)
    except Exception:              # noqa: BLE001 — a janela de erro nunca pode derrubar o app
        log.exception("Falha ao mostrar a janela de erro")
    finally:
        _handling.busy = False


def qt_message_handler(mode, context, message) -> None:
    """Avisos internos do Qt vão para o log em vez de sumirem no console."""
    from PySide6.QtCore import QtMsgType
    level = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
             QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
             QtMsgType.QtFatalMsg: logging.CRITICAL}.get(mode, logging.WARNING)
    logging.getLogger("finora.qt").log(level, message)
