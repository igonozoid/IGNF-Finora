from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QDialog, QPushButton

from finora.ui import reconcile_page
from tests.ui.conftest import pump

OFX = Path(__file__).parents[1] / "data" / "extrato.ofx"


def _ofx_this_month(tmp_path) -> str:
    """O extrato de exemplo, com as datas trazidas para o mês atual (casa com os lançamentos do `sample`)."""
    ym = date.today().strftime("%Y%m").encode()
    path = tmp_path / "extrato.ofx"
    path.write_bytes(OFX.read_bytes().replace(b"202610", ym))
    return str(path)


def test_importar_confirmar_criar_ignorar(plus, window, dialogs, tmp_path, qtbot, monkeypatch):
    window.go_to("reconcile")
    page = window.page("reconcile")
    assert "Importar OFX" in page.empty.text()
    dialogs.open_path = _ofx_this_month(tmp_path)
    page.import_btn.click()
    pump(qtbot)
    assert page.table.rowCount() >= 3 and "4 linhas novas" in window.statusBar().currentMessage()

    def row_of(memo):
        return next(r for r, ln in enumerate(page.rows) if ln.memo.startswith(memo))

    def click(memo, text):
        w = page.table.cellWidget(row_of(memo), reconcile_page.C_ACT)
        next(b for b in w.findChildren(QPushButton) if b.text() == text).click()
        pump(qtbot)

    # o sample tem "Conta de luz" de R$ 180,40 em aberto: vira sugestão; confirmar marca como paga
    luz = page.rows[row_of("PAG BOLETO")]
    if luz.suggestion.kind == "entry":
        click("PAG BOLETO", "Confirmar")
        assert "Conciliado" in window.statusBar().currentMessage()
    # criar a tarifa pelo diálogo (aceito automaticamente)
    monkeypatch.setattr(reconcile_page.CreateDialog, "exec", lambda self: QDialog.Accepted)
    click("TAR PACOTE", "Criar")
    assert "criado" in window.statusBar().currentMessage()
    click("DEB AUT", "Ignorar")
    assert all(not ln.memo.startswith(("TAR", "DEB")) for ln in page.rows)
    page.show_btns["all"].click()
    pump(qtbot)
    assert page.table.rowCount() == 4 and "conciliadas" in page.summary.text()


def test_importar_pelo_botao_de_lancamentos(plus, window, dialogs, tmp_path, qtbot):
    dialogs.open_path = _ofx_this_month(tmp_path)
    window.go_to("entries")
    window.page("entries").ofx_btn.click()
    pump(qtbot)
    assert window.current_key() == "reconcile" and "4 linhas novas" in window.statusBar().currentMessage()


def test_conciliacao_bloqueada_na_free(window, qtbot):
    window.go_to("reconcile")
    page = window.page("reconcile")
    assert page.locked and not hasattr(page, "table")
