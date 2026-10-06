from datetime import date

from PySide6.QtCore import QDate

from finora.core import db
from finora.services import period_lock
from tests.ui.conftest import pump


def test_fechar_periodo_e_lancamento_vira_so_leitura(plus, window, dialogs, qtbot):
    window.go_to("settings")
    page = window.page("settings")
    assert "Nenhum período fechado" in page.lock_status.text()
    today = date.today()
    page.lock_date.setDate(QDate(today.year, today.month, today.day))
    page.lock_btn.click()                                        # dialogs responde "Sim"
    assert f"Fechado até {today:%d/%m/%Y}" in page.lock_status.text()

    # abrir um lançamento do mês: aviso e sem excluir; salvar uma alteração dá erro amigável
    window.go_to("entries")
    ep = window.page("entries")
    mercado = next(e for e in ep.model.rows if e.description == "Mercado")
    ep.open_by_id(mercado.id)
    form = ep.form
    assert "Período fechado" in form.series_info.text() and not form.delete_btn.isEnabled()
    form.desc.setText("Mercado do mês")
    form._save()
    assert "está fechado" in form.error.text()

    window.go_to("settings")
    page.unlock_btn.click()
    pump(qtbot)
    with db.Session() as s:
        assert period_lock.locked_through(s, window.profile.id) is None


def test_fechamento_bloqueado_na_free(window):
    assert window.page("settings").lock_date is None
