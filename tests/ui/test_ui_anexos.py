from PySide6.QtGui import QDesktopServices

from finora.ui import attachments_box
from tests.ui.conftest import pump


def _open_entry(window, desc):
    page = window.page("entries")
    window.go_to("entries")
    e = next(x for x in page.model.rows if x.description == desc)
    page.open_by_id(e.id)
    return page, e


def test_anexar_abrir_e_remover(plus, window, dialogs, tmp_path, qtbot, monkeypatch):
    page, e = _open_entry(window, "Conta de luz")
    box = page.form.attach
    assert box.add_btn.isEnabled() and "Nenhum comprovante" in box.hint.text()
    f = tmp_path / "boleto.pdf"
    f.write_bytes(b"%PDF-1.4 boleto")
    dialogs.open_path = str(f)
    box.add_btn.click()
    pump(qtbot)
    assert box.list.count() == 1 and "boleto.pdf" in box.list.item(0).text()
    assert "anexado" in window.statusBar().currentMessage()
    row = next(i for i, x in enumerate(page.model.rows) if x.id == e.id)
    assert page.model.data(page.model.index(row, 2), 1) is not None          # clipe na descrição

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    monkeypatch.setattr(attachments_box, "OPEN_DIR", tmp_path / "abertos")
    box.list.setCurrentRow(0)
    box.open_btn.click()
    assert opened and (tmp_path / "abertos").exists()

    dialogs.save_path = str(tmp_path / "copia.pdf")
    box.save_btn.click()
    assert (tmp_path / "copia.pdf").read_bytes() == b"%PDF-1.4 boleto"

    box.remove_btn.click()                                                  # dialogs responde "Sim"
    assert box.list.count() == 0


def test_novo_lancamento_pede_para_salvar_antes(plus, window):
    page = window.page("entries")
    window.go_to("entries")
    page.new_entry()
    box = page.form.attach
    assert not box.add_btn.isEnabled() and "Salve o lançamento" in box.hint.text()


def test_anexos_bloqueados_na_free(window, dialogs):
    page, _e = _open_entry(window, "Mercado")
    box = page.form.attach
    assert box.locked
    box.add_btn.click()
    assert dialogs.shown                                                    # convite para upgrade
