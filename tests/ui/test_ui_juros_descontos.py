"""Juros e descontos na tela de Relatórios (Fase 3.11): Plus/Pro (D3)."""
from datetime import date, timedelta
from decimal import Decimal as D

from finora.core import db
from finora.services import accounts, entries
from finora.services.entries import EntryData


def test_juros_e_descontos_na_tela(plus, window, profile):
    today = date.today()
    with db.Session() as s:
        bank = accounts.list_accounts(s, profile.id)[0].id
        eid = entries.create(s, profile.id, EntryData(kind="expense", description="Boleto", amount=D("200"),
                                                      due_date=today - timedelta(days=3), account_id=bank,
                                                      contact="Loja"))
        entries.pay(s, eid, today, amount=D("210"))
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "interest"))
    view = rp.views["interest"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    row = [view.table.item(0, c).text() for c in range(view.table.columnCount())]
    assert row[2:4] == ["Boleto", "Loja"] and row[6].endswith("10,00") and row[7] == "3 d"
    assert "Juros e multas pagos <b>R$ 10,00</b>" in view.footer.text()
    view.kind.setCurrentIndex(view.kind.findData("income"))
    assert view.table.rowCount() == 0 and "Nenhuma conta paga" in view.empty.text()


def test_juros_e_descontos_bloqueado_na_free(window, dialogs):
    rp = window.page("reports")
    b = next(b for b, _l, key in rp.buttons if key == "interest")
    assert not b.isCheckable()
    b.click()
    assert any("Plus e Pro" in x for x in dialogs.shown)
