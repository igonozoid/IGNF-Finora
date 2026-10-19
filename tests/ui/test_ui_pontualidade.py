"""Relatório de pontualidade na tela de Relatórios (Fase 3.1): Plus/Pro (D3)."""
from datetime import date, timedelta
from decimal import Decimal as D

from finora.core import db
from finora.services import accounts, entries
from finora.services.entries import EntryData


def _pay_late(profile):
    today = date.today()
    with db.Session() as s:
        bank = accounts.list_accounts(s, profile.id)[0].id
        entries.create(s, profile.id, EntryData(kind="income", description="Serviço", amount=D("800"),
                                                due_date=today - timedelta(days=12), account_id=bank,
                                                contact="Cliente Atrasado", paid=True, paid_date=today))


def test_pontualidade_na_tela(plus, window, profile):
    _pay_late(profile)
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "punctuality"))
    view = rp.views["punctuality"]
    table = [[view.table.item(r, c).text() for c in range(view.table.columnCount())]
             for r in range(view.table.rowCount())]
    assert table[0][:5] == ["Cliente Atrasado", "1", "0", "1", "12 dias"] and table[0][6] == "12 d atraso"
    assert table[-1][0] == "Total" and view.table.item(len(table) - 1, 0).font().bold()
    assert "com atraso" in view.footer.text() and "12 dias" in view.footer.text()
    sheet = view.export_sheet()
    assert sheet.title == "Pontualidade" and sheet.subtitle.startswith("Recebimentos (clientes)")
    view.kind.setCurrentIndex(view.kind.findData("expense"))
    assert view.table.rowCount() == 0 and "Nenhum lançamento pago" in view.empty.text()


def test_pontualidade_bloqueada_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "punctuality")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
