from decimal import Decimal as D

from finora.core import db
from finora.services import budgets, categories
from tests.ui.conftest import pump


def _open_budget(window):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "budget"))
    view = rp.views["budget"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    return view


def test_definir_orcamento_na_tabela_e_ver_consumo(plus, window, dialogs, qtbot):
    view = _open_budget(window)
    row = next(i for i, r in enumerate(view._data) if r.name == "Supermercado")
    view.table.item(row, 1).setText("1.000,00")                 # como se tivesse digitado na célula
    pump(qtbot)
    r = next(x for x in view._data if x.name == "Supermercado")
    assert r.own == 1000 and r.actual == D("640.10") and r.status == "ok"
    assert "Orçamento de Supermercado" in window.statusBar().currentMessage()
    group = next(x for x in view._data if x.name == "Alimentação")
    assert group.monthly == 1000 and view.table.item(view._data.index(group), 6).text() == "64%"
    # valor inválido avisa e não grava
    row = next(i for i, r in enumerate(view._data) if r.name == "Supermercado")
    view.table.item(row, 1).setText("abc")
    assert any("inválido" in m for m in dialogs.shown)
    view.only_used.setChecked(True)
    assert all(r.own or r.monthly or r.actual for r in view._data)


def test_aviso_ao_lancar_despesa_que_estoura(plus, window, qtbot):
    with db.Session() as s:
        luz = dict((label, cid) for cid, label in categories.choices(s, window.profile.id, "expense"))["Moradia › Luz"]
        budgets.set_budget(s, window.profile.id, luz, 100)
    page = window.page("entries")
    window.go_to("entries")
    conta = next(e for e in page.model.rows if e.description == "Conta de luz")
    page.open_by_id(conta.id)
    page.form._save()
    pump(qtbot)
    assert "Luz passou do orçamento" in window.statusBar().currentMessage()


def test_orcamento_bloqueado_na_free(window):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "budget")
    assert not b.isCheckable()
