from PySide6.QtWidgets import QPushButton

from finora.core import settings
from finora.services import updates
from finora.ui import terms_dialog


def test_termos_so_liberam_depois_de_aceitar(qtbot, app_t):
    dlg = terms_dialog.TermsDialog(ask=True)
    qtbot.addWidget(dlg)
    ok = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Continuar")
    assert not ok.isEnabled()
    dlg.accept_chk.setChecked(True)
    assert ok.isEnabled()
    text = terms_dialog.terms_text()
    assert "LGPD" in text and "telemetria" in text and "BrasilAPI" in text


def test_aviso_de_versao_nova_na_barra(window):
    window.show_update(updates.Release("9.9.9", "https://example.com/v9", None, ""))
    assert "9.9.9" in window.update_link.text()


def test_opcao_de_avisar_versao_nova(window):
    window.go_to("settings")
    page = window.page("settings")
    page.update_chk.setChecked(False)
    assert settings.get_update_check() is False
