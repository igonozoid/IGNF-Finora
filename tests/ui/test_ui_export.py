from openpyxl import load_workbook

from tests.ui.conftest import pump


def test_exportar_lancamentos_e_relatorios(plus, window, dialogs, tmp_path, qtbot):
    window.go_to("entries")
    page = window.page("entries")
    assert page.export_btn.menu() is not None                    # Plus: menu Excel / PDF
    dialogs.save_path = str(tmp_path / "lanc")                   # sem extensão: o app completa
    page._export("xlsx")
    ws = load_workbook(tmp_path / "lanc.xlsx").active
    descr = [ws.cell(r, 3).value for r in range(5, ws.max_row + 1)]
    assert "Salário" in descr and "Mercado" in descr

    window.go_to("reports")
    exported = 0
    for key, view in window.page("reports").views.items():
        view.refresh()
        pump(qtbot)
        sheet = view.export_sheet()
        if sheet is None or not sheet.rows:
            continue
        dialogs.save_path = str(tmp_path / f"{key}.pdf")
        view.export_btns[1].click()                              # botão "PDF"
        assert (tmp_path / f"{key}.pdf").read_bytes()[:4] == b"%PDF", key
        exported += 1
    assert exported >= 5


def test_exportar_bloqueado_na_free(window, dialogs):
    page = window.page("entries")
    assert page.export_btn.menu() is None
    page.export_btn.click()
    assert dialogs.shown, "deveria convidar para o upgrade"
