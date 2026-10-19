"""Fluxo de caixa por centro (Fase 3.8, relatório do MCC)."""
import json
import shutil
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from finora.services import accounts, cost_centers, entries, reports
from finora.services.entries import EntryData
from finora.services.mcc_import import mapper, reader

DATA = Path(__file__).parent / "data"


def test_fluxo_por_centro(session, profile, plus):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    trator = cost_centers.create(s, eid, "Trator", None)
    loja = cost_centers.create(s, eid, "Loja", None)

    def add(kind, amount, due, center=None, paid=None):
        entries.create(s, eid, EntryData(kind=kind, description="x", amount=D(amount), due_date=due, account_id=bank,
                                         cost_center_id=center, paid=paid is not None, paid_date=paid))

    add("expense", "300", date(2026, 5, 25), trator, paid=date(2026, 6, 2))     # pago no período (pela data)
    add("expense", "200", date(2026, 6, 20), trator)                             # a pagar no período
    add("expense", "999", date(2026, 7, 5), trator)                              # vence depois: fora
    add("income", "1000", date(2026, 6, 10), loja, paid=date(2026, 6, 10))
    add("income", "400", date(2026, 6, 30), loja)
    add("expense", "50", date(2026, 6, 15), None, paid=date(2026, 6, 15))       # sem centro
    rows = reports.center_flow(s, eid, date(2026, 6, 1), date(2026, 6, 30))
    assert [r.name for r in rows] == ["Loja", "Trator", reports.NO_CENTER]
    by = {r.name: r for r in rows}
    t = by["Trator"]
    assert (t.paid, t.received, t.to_pay, t.to_receive, t.realized, t.forecast) == \
        (D("300.00"), D("0.00"), D("200.00"), D("0.00"), D("-300.00"), D("-200.00"))
    lj = by["Loja"]
    assert (lj.received, lj.to_receive, lj.realized, lj.forecast) == (D("1000.00"), D("400.00"), D("1000.00"),
                                                                       D("400.00"))
    total = reports.center_flow_total(rows)
    assert (total.paid, total.received, total.to_pay, total.to_receive) == (D("350.00"), D("1000.00"), D("200.00"),
                                                                            D("400.00"))


def test_bate_com_o_mcc_de_exemplo(session, plus, tmp_path):
    """Os totais do fluxo por centro batem com os do MCC (gabarito do banco de exemplo), empresa por empresa."""
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    gabarito = json.loads((DATA / "mcc_exemplo_gabarito.json").read_text(encoding="utf-8"))
    with reader.open_copy(p) as con:
        r = mapper.import_companies(session, con)
    for mcc_id, g in gabarito["por_empresa"].items():
        total = reports.center_flow_total(reports.center_flow(session, r.entities[int(mcc_id)], date(2000, 1, 1),
                                                              date(2030, 12, 31)))
        assert (total.paid, total.received, total.to_pay, total.to_receive) == \
            tuple(D(str(g[k])) for k in ("pago", "recebido", "a_pagar", "a_receber")), mcc_id
