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
