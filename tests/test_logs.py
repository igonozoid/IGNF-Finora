import sys
import threading

import pytest

from finora.core import logs


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = logs.setup(tmp_path / "finora.log")
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)          # restaura depois do teste
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    yield path
    logs.set_error_handler(None)
    for h in list(logs.log.handlers):
        logs.log.removeHandler(h)
        h.close()


def _raise():
    try:
        raise ValueError("deu ruim aqui")
    except ValueError:
        return sys.exc_info()


def test_inicio_de_sessao_vai_para_o_arquivo(log_file, tmp_path):
    logs.session_start(tmp_path)
    text = log_file.read_text(encoding="utf-8")
    assert "IGNF Finora" in text and "Python" in text and str(tmp_path) in text


def test_erro_inesperado_e_registrado_e_mostrado(log_file):
    shown = []
    logs.set_error_handler(lambda summary, details: shown.append((summary, details)))
    sys.excepthook(*_raise())
    assert shown and shown[0][0] == "ValueError: deu ruim aqui" and "Traceback" in shown[0][1]
    text = log_file.read_text(encoding="utf-8")
    assert "CRITICAL" in text and "deu ruim aqui" in text and "test_logs.py" in text


def test_erro_em_thread_tambem_e_registrado(log_file):
    shown = []
    logs.set_error_handler(lambda s, d: shown.append(s))
    t = threading.Thread(target=lambda: 1 / 0)
    t.start()
    t.join()
    assert shown == ["ZeroDivisionError: division by zero"]
    assert "ZeroDivisionError" in log_file.read_text(encoding="utf-8")


def test_erro_dentro_da_janela_de_erro_nao_derruba_nem_repete(log_file):
    calls = []

    def broken(summary, details):
        calls.append(summary)
        raise RuntimeError("a janela falhou")

    logs.set_error_handler(broken)
    sys.excepthook(*_raise())                  # não pode levantar exceção
    assert calls == ["ValueError: deu ruim aqui"]
    assert "Falha ao mostrar a janela de erro" in log_file.read_text(encoding="utf-8")


def test_rotacao_limita_o_tamanho(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "MAX_BYTES", 2_000)
    path = logs.setup(tmp_path / "finora.log")
    for i in range(200):
        logs.log.info("linha %03d %s", i, "x" * 40)
    files = sorted(p.name for p in tmp_path.glob("finora.log*"))
    assert files == ["finora.log", "finora.log.1", "finora.log.2", "finora.log.3"]
    assert path.stat().st_size <= 2_000
    for h in list(logs.log.handlers):
        logs.log.removeHandler(h)
        h.close()
