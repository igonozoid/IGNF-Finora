"""Fluxo por centro na tela de Relatórios (Fase 3.8): Plus/Pro (D3)."""
from datetime import date
from decimal import Decimal as D

from finora.core import db
from finora.services import accounts, cost_centers, entries
from finora.services.entries import EntryData


def test_fluxo_por_centro_na_tela(plus, window, profile):
    today = date.today()
    with db.Session() as s:
        bank = accounts.list_accounts(s, profile.id)[0].id
        cc = cost_centers.create(s, profile.id, "Trator", None)
        entries.create(s, profile.id, EntryData(kind="expense", description="Peça", amount=D("150"), due_date=today,
                                                account_id=bank, cost_center_id=cc))
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "center_flow"))
    view = rp.views["center_flow"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    names = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert names[0] == "Trator" and names[-1] == "Total"
    trator = [view.table.item(0, c).text() for c in range(view.table.columnCount())]
    assert trator[3].endswith("150,00") and trator[1] == ""
    assert view.export_sheet().title == "Fluxo por centro"


def test_fluxo_por_centro_bloqueado_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "center_flow")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
