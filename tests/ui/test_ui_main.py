from decimal import Decimal as D

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from finora.core import db, logs, settings
from finora.services import accounts, categories, setup
from finora.ui.main_window import KEYS, NAV, SHOW_NEW_ENTRY


def test_todas_as_telas_abrem(window, qtbot):
    for i, (key, _icon, label, *_r) in enumerate(NAV):
        window.go_to(i)
        qtbot.wait(10)
        assert window.stack.currentIndex() == i and window.header.title.text() == label
        assert window.header.new_btn.isVisible() == (key in SHOW_NEW_ENTRY)


def test_atalhos_de_teclado(window, qtbot):
    qtbot.keyClick(window, Qt.Key_4, Qt.ControlModifier)
    assert window.current_key() == "categories"
    qtbot.keyClick(window, Qt.Key_N, Qt.ControlModifier)          # Ctrl+N vale em qualquer tela
    assert window.current_key() == "entries" and window.page("entries").form_scroll.isVisible()


def test_tema_alterna_e_fica_salvo(window):
    assert window.theme_name == "light"
    window.toggle_theme()
    assert window.theme_name == "dark" and settings.get_theme() == "dark"
    assert window.page("settings").theme_box.currentData() == "dark"
    assert window.sidebar.theme_btn.text() == "Tema claro"


def test_tres_formatos_de_menu(window):
    window.set_nav("rail")
    assert window.sidebar.isVisible() and window.sidebar.width() == 52 and not window.tabs.isVisible()
    window.set_nav("tabs")
    assert not window.sidebar.isVisible() and window.tabs.isVisible()
    i = KEYS.index("contacts")
    window.tabs.group.button(i).click()
    assert window.current_key() == "contacts" and window.sidebar.group.checkedId() == i
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


def test_busca_global_ctrl_k(window, qtbot):
    qtbot.keyClick(window, Qt.Key_K, Qt.ControlModifier)
    search = window.header.search
    assert search.hasFocus()
    search.setText("merc")
    search.textEdited.emit("merc")
    hits = [search.model.item(r).data(Qt.UserRole) for r in range(search.model.rowCount())]
    entry = next(h for h in hits if h is not None and h.kind == "entry")
    assert entry.title == "Mercado"
    search._activated(search.model.index(hits.index(entry), 0))
    assert window.current_key() == "entries" and window.page("entries").form.editing.description == "Mercado"
    assert search.text() == ""


def test_busca_abre_contato_conta_e_categoria(window):
    from finora.services import search as svc
    from finora.core import db
    with db.Session() as s:
        hits = {h.kind: h for h in svc.search(s, window.profile.id, "en") + svc.search(s, window.profile.id, "Nubank")
                + svc.search(s, window.profile.id, "Luz")}
    window.open_hit(hits["contact"])
    assert window.current_key() == "contacts" and window.page("contacts").form.title.text() == hits["contact"].title
    window.open_hit(hits["account"])
    assert window.current_key() == "accounts" and window.page("accounts").editing.name == "Nubank"
    window.open_hit(hits["category"])
    assert window.current_key() == "categories" and window.page("categories").current.name == "Luz"


def test_periodo_no_cabecalho(window):
    from datetime import date
    chip = window.header.period
    window.go_to("entries")
    assert chip.isVisible()
    today = date.today()
    chip.shift(-1)
    entries_page = window.page("entries")
    assert (entries_page.year, entries_page.month) == (chip.year, chip.month) != (today.year, today.month)
    assert window.page("dashboard").period == (chip.year, chip.month)              # Dashboard acompanha
    entries_page._shift_month(2)                                          # mudou dentro de Lançamentos
    assert (chip.year, chip.month) == (entries_page.year, entries_page.month)
    entries_page.filter_group.button(3).click()                           # Atrasados: mês não importa
    assert not chip.prev.isEnabled()
    window.go_to("categories")
    assert not chip.isVisible()


def test_botao_recolhe_menu_e_abas_so_icones(window):
    window.sidebar.collapse_btn.click()
    assert window.nav_mode == "rail" and settings.get_nav() == "rail"
    window.sidebar.collapse_btn.click()
    assert window.nav_mode == "sidebar"
    window.set_nav("tabs")
    window.tabs.icons_btn.click()
    assert settings.get_tabs_icons() and all(b.text() == "" for b, _i, _l in window.tabs.buttons)
    window.tabs.icons_btn.click()
    assert not settings.get_tabs_icons()


def test_sobre_mostra_a_desenvolvedora(window):
    from PySide6.QtWidgets import QLabel
    window.go_to("settings")
    texts = " ".join(l.text() for l in window.page("settings").findChildren(QLabel))
    assert "IGNF Projetos e Serviços de Engenharia" in texts and "ignf.com.br/contato" in texts
