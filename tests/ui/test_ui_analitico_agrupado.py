"""Analítico com agrupamentos livres na tela (Fase 3.9): agrupar é Plus/Pro (D3); sem agrupar continua livre."""


def _view(window):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "analytical"))
    view = rp.views["analytical"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    return view


def _col(view, c):
    return [view.table.item(r, c).text() for r in range(view.table.rowCount())]


def test_agrupar_o_analitico(plus, window, sample):
    view = _view(window)
    plain = view.table.rowCount()
    assert not view.group2.isEnabled() and not view.mode.isEnabled()
    view.group1.setCurrentIndex(view.group1.findData("kind"))
    assert view.group2.isEnabled() and view.mode.isEnabled()
    desc = _col(view, 1)
    assert desc[0].startswith("Receitas (") and any(d.startswith("Despesas (") for d in desc)
    assert view.table.rowCount() == plain + 2                          # 2 cabeçalhos + os mesmos lançamentos
    view.group2.setCurrentIndex(view.group2.findData("contact"))
    assert any(d.strip().startswith("Empresa X (") for d in _col(view, 1))
    view.mode.setCurrentIndex(view.mode.findData("total"))
    assert all(r == "" for r in _col(view, 0))                         # totalizado: só grupos, sem datas
    assert view.export_sheet().subtitle.endswith("por tipo e contato (totalizado)")
    view.group2.setCurrentIndex(view.group2.findData("kind"))          # o mesmo nos dois níveis: volta a 1 nível
    assert view.group2.currentData() is None
    view.group1.setCurrentIndex(0)
    assert view.table.rowCount() == plain and not view.mode.isEnabled()


def test_agrupar_bloqueado_na_free(window, sample, dialogs):
    view = _view(window)
    plain = view.table.rowCount()
    view.group1.setCurrentIndex(view.group1.findData("contact"))
    assert view.group1.currentData() is None and any("Plus e Pro" in x for x in dialogs.shown)
    assert view.table.rowCount() == plain                              # o analítico simples continua
