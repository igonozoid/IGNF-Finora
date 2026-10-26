"""Entidade com a DRE de empresa (PJ, como a importada do MCC): o app abre e todas as telas e relatórios funcionam
(antes, o painel procurava "= Sobra do mês", que só existe na DRE pessoal, e o app quebrava ao abrir)."""
from finora.core import db
from finora.models import Entity
from finora.services import categories


def test_todas_as_telas_com_dre_de_empresa(qtbot, qapp, app_t, plus, sample, dialogs):
    from finora.ui.main_window import KEYS, MainWindow
    from finora.ui.reports_page import REPORTS
    with db.Session() as s:
        categories.convert_model(s, sample.id, "business")
        s.get(Entity, sample.id).dre_model = "business"
        s.commit()
    w = MainWindow(sample)                                 # abre no painel: era aqui que quebrava
    w.restart = lambda: None
    try:
        assert w.page("dashboard").k_result.value.text().startswith("R$")
        for key in KEYS:
            w.go_to(key)
        rp = w.page("reports")
        w.go_to("reports")
        for i, (key, *_rest) in enumerate(REPORTS):
            rp._select(i)
            assert rp.views[key] is rp.stack.currentWidget()
    finally:
        w.close()
        w.deleteLater()
