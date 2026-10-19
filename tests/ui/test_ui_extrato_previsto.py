"""Extrato por conta no modo previsto (Fase 3.5): Plus/Pro (D3); o extrato normal continua livre."""


def _statement(window):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "statement"))
    view = rp.views["statement"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    return view


def _texts(view):
    return [view.table.item(r, 1).text() for r in range(view.table.rowCount())]


def test_extrato_previsto_na_tela(plus, window, sample):
    view = _statement(window)
    assert not any("(em aberto)" in t for t in _texts(view))
    view.forecast.setChecked(True)
    assert any(t == "Mercado (em aberto)" for t in _texts(view))       # em aberto no mês, em cinza
    assert "Saldo final previsto" in view.footer.text()
    assert view.export_sheet().subtitle.endswith("· previsto")


def test_extrato_previsto_bloqueado_na_free(window, sample, dialogs):
    view = _statement(window)
    view.forecast.setChecked(True)
    assert not view.forecast.isChecked() and any("Plus e Pro" in x for x in dialogs.shown)
    assert not any("(em aberto)" in t for t in _texts(view))
