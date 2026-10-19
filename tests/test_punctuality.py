"""Análise de pontualidade (Fase 3.1, relatório do MCC)."""
from datetime import date
from decimal import Decimal as D

from finora.services import accounts, entries, reports
from finora.services.entries import EntryData


def _add(s, eid, bank, kind, contact, due, paid=None, amount="100"):
    return entries.create(s, eid, EntryData(kind=kind, description="x", amount=D(amount), due_date=due,
                                            account_id=bank, contact=contact, paid=paid is not None,
                                            paid_date=paid))


def test_pontualidade_por_contato(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    _add(s, eid, bank, "income", "Maria", date(2026, 3, 10), date(2026, 3, 10))          # no dia
    _add(s, eid, bank, "income", "Maria", date(2026, 4, 10), date(2026, 4, 25))          # 15 de atraso
    _add(s, eid, bank, "income", "Maria", date(2026, 5, 10), date(2026, 5, 7), "300")    # 3 antes
    _add(s, eid, bank, "income", "João", date(2026, 3, 1), date(2026, 3, 31))            # 30 de atraso
    _add(s, eid, bank, "income", None, date(2026, 3, 5), date(2026, 3, 4))               # sem contato, 1 antes
    _add(s, eid, bank, "income", "Maria", date(2026, 6, 10))                             # em aberto: fora
    _add(s, eid, bank, "expense", "Enel", date(2026, 3, 10), date(2026, 3, 12))          # despesa: outro filtro
    _add(s, eid, bank, "income", "Maria", date(2025, 12, 1), date(2025, 12, 20))         # pago fora do período

    rows = reports.punctuality(s, eid, date(2026, 1, 1), date(2026, 12, 31), "income")
    by = {r.contact: r for r in rows}
    assert [r.contact for r in rows] == ["João", "Maria", reports.NO_CONTACT]   # mais atrasos primeiro
    m = by["Maria"]
    assert (m.count, m.on_time, m.late, m.max_late, m.max_early, m.average, m.amount) == \
        (3, 2, 1, 15, 3, D("4.0"), D("500.00"))
    assert (by["João"].max_late, by["João"].average, by["João"].late_share) == (30, D("30.0"), 100)
    assert (by[reports.NO_CONTACT].max_early, by[reports.NO_CONTACT].max_late) == (1, 0)
    total = reports.punctuality_total(rows)
    assert (total.count, total.late, total.max_late, total.max_early, total.average) == (5, 2, 30, 3, D("8.2"))

    (enel,) = reports.punctuality(s, eid, date(2026, 1, 1), date(2026, 12, 31), "expense")
    assert (enel.contact, enel.max_late) == ("Enel", 2)
    assert reports.punctuality_total([]) is None
