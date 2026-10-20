from PySide6.QtWidgets import QWidget

from finora.core import single_instance


def test_segundo_finora_so_traz_a_janela_do_primeiro(qtbot, tmp_path):
    name = single_instance.name_for(tmp_path)
    assert not single_instance.already_running(name)
    single_instance.listen(name)
    try:
        w = QWidget()
        qtbot.addWidget(w)
        single_instance.window = w                 # escondida, como na bandeja
        assert w.isHidden()
        assert single_instance.already_running(name)
        qtbot.waitUntil(lambda: not w.isHidden(), timeout=3000)
    finally:
        single_instance.stop()
        single_instance.window = None
    assert not single_instance.already_running(name)


def test_nome_do_canal_depende_da_pasta(tmp_path):
    assert single_instance.name_for(tmp_path / "a") != single_instance.name_for(tmp_path / "b")


def test_segundo_finora_libera_a_janela_da_frente(qtbot, tmp_path, monkeypatch):
    """No Windows quem foi aberto agora libera a vez; o primeiro pede atenção (pisca) se ainda assim não vier."""
    from PySide6.QtWidgets import QApplication
    calls, alerts = [], []
    monkeypatch.setattr(single_instance, "allow_foreground", lambda: calls.append(1))
    monkeypatch.setattr(QApplication, "alert", staticmethod(lambda w, ms=0: alerts.append(w)))
    name = single_instance.name_for(tmp_path)
    assert not single_instance.already_running(name) and calls == []     # sozinho: não libera nada
    single_instance.listen(name)
    try:
        w = QWidget()
        qtbot.addWidget(w)
        single_instance.window = w
        assert single_instance.already_running(name) and calls == [1]
        qtbot.waitUntil(lambda: alerts == [w], timeout=3000)
    finally:
        single_instance.stop()
        single_instance.window = None
