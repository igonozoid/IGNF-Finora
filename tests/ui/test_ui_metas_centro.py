"""Metas por centro (orçamento / projeção) na tela de Relatórios (Fase 3.7): Plus/Pro (D3)."""
from datetime import date
from decimal import Decimal as D

from finora.core import db
from finora.services import accounts, cost_centers, entries
from finora.services.entries import EntryData


def test_metas_por_centro_na_tela(plus, window, profile):
    today = date.today()
    with db.Session() as s:
        bank = accounts.list_accounts(s, profile.id)[0].id
        cc = cost_centers.create(s, profile.id, "Trator", D("100"), applies_income=False)
        entries.create(s, profile.id, EntryData(kind="expense", description="Peça", amount=D("150"), due_date=today,
                                                account_id=bank, cost_center_id=cc))
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "center_targets"))
    view = rp.views["center_targets"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    row = [view.table.item(0, c).text() for c in range(view.table.columnCount())]
    assert row[0] == "Trator" and row[4] == "150,0%" and row[5].startswith(("−", "-"))
    view.paid_only.setChecked(True)
    assert view.table.horizontalHeaderItem(3).text() == "PAGO" and view.table.item(0, 4).text() == "0,0%"
    view.kind.setCurrentIndex(view.kind.findData("income"))
    assert view.table.rowCount() == 0 and "centro de lucro" in view.empty.text()


def test_metas_por_centro_bloqueado_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "center_targets")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
