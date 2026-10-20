"""Relatório de cadastros na tela de Relatórios (Fase 3.10): Plus/Pro (D3)."""


def _view(window):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "register"))
    return rp.views["register"]


def test_cadastros_na_tela_e_abre_o_contato(plus, window, sample):
    view = _view(window)
    names = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert {"Empresa X", "Enel", "Imobiliária"} <= set(names)
    assert "contato(s)" in view.footer.text()
    view.role.setCurrentIndex(view.role.findData("customer"))
    customers = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert "Empresa X" in customers and "Enel" not in customers
    assert view.export_sheet().subtitle == "Me paga"
    view._double(customers.index("Empresa X"), 0)                     # dois cliques: vai para o cadastro
    assert window.current_key() == "contacts"
    assert window.page("contacts").form.current.name == "Empresa X"


def test_cadastros_bloqueado_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "register")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
