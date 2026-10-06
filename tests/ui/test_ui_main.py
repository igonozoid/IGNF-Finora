from decimal import Decimal as D

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from finora.core import db, logs, settings
from finora.services import accounts, categories, setup
from finora.ui.main_window import NAV, SHOW_NEW_ENTRY


def test_todas_as_telas_abrem(window, qtbot):
    for i, (_icon, label, *_r) in enumerate(NAV):
        window.go_to(i)
        qtbot.wait(10)
        assert window.stack.currentIndex() == i and window.header.title.text() == label
        assert window.header.new_btn.isVisible() == (i in SHOW_NEW_ENTRY)


def test_atalhos_de_teclado(window, qtbot):
    qtbot.keyClick(window, Qt.Key_4, Qt.ControlModifier)
    assert window.stack.currentIndex() == 3
    qtbot.keyClick(window, Qt.Key_N, Qt.ControlModifier)          # Ctrl+N vale em qualquer tela
    assert window.stack.currentIndex() == 1 and window.pages[1].form_scroll.isVisible()


def test_tema_alterna_e_fica_salvo(window):
    assert window.theme_name == "light"
    window.toggle_theme()
    assert window.theme_name == "dark" and settings.get_theme() == "dark"
    assert window.pages[6].theme_box.currentData() == "dark"
    assert window.sidebar.theme_btn.text() == "Tema claro"


def test_tres_formatos_de_menu(window):
    window.set_nav("rail")
    assert window.sidebar.isVisible() and window.sidebar.width() == 52 and not window.tabs.isVisible()
    window.set_nav("tabs")
    assert not window.sidebar.isVisible() and window.tabs.isVisible()
    window.tabs.group.button(4).click()
    assert window.stack.currentIndex() == 4 and window.sidebar.group.checkedId() == 4
    window.set_nav("sidebar")
    assert window.sidebar.width() == 200 and settings.get_nav() == "sidebar"


def test_janela_pequena(window, qtbot):
    window.resize(800, 480)
    for i in range(len(NAV)):
        window.go_to(i)
        qtbot.wait(10)
    assert window.width() == 800


def test_assistente_de_primeiro_uso(qtbot, app_t, data_dir):
    from finora.ui.first_run import FirstRunWizard
    w = FirstRunWizard(app_t)
    qtbot.addWidget(w)
    w.show()
    w.next_btn.click()
    assert w.error.isVisible() and w.pages.currentIndex() == 0          # nome é obrigatório
    w.name_edit.setText("Marina")
    w.next_btn.click()
    w.kind_box.setCurrentIndex(w.kind_box.findData("card"))
    assert w.acc_name_edit.text() == "Cartão de crédito" and w.balance_lbl.label.text() == "Fatura em aberto"
    w.balance_edit.setText("abc")
    w.next_btn.click()
    assert w.pages.currentIndex() == 1 and "inválido" in w.error.text()
    w.balance_edit.setText("1.250,40")
    w.next_btn.click()
    w.next_btn.click()                                                   # Concluir
    assert w.result() == 1 and w.profile.name == "Marina"
    with db.Session() as s:
        acc = accounts.list_accounts(s, w.profile.id)[0]
        assert acc.balance == D("-1250.40") and len(categories.tree(s, w.profile.id)) == 9
        assert not setup.needs_setup(s)


def test_erro_num_clique_vai_para_o_log_e_o_app_continua(window, qtbot, tmp_path, monkeypatch):
    import sys
    import threading
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    log_file = logs.setup(tmp_path / "finora.log")
    shown = []
    logs.set_error_handler(lambda summary, details: shown.append(summary))
    try:
        b = QPushButton("quebrar", window)
        b.clicked.connect(lambda: {}["nao-existe"])
        b.click()
        assert shown == ["KeyError: 'nao-existe'"]
        assert "nao-existe" in log_file.read_text(encoding="utf-8")
        assert window.isVisible()
    finally:
        logs.set_error_handler(None)
        for h in list(logs.log.handlers):
            logs.log.removeHandler(h)
            h.close()
