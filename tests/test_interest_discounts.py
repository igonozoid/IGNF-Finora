"""Juros e descontos na baixa (Fase 3.11, relatório do MCC)."""
from datetime import date
from decimal import Decimal as D

from finora.services import accounts, entries, reports
from finora.services.entries import EntryData


def test_juros_e_descontos(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id

    def bill(kind, amount, due, contact="Fornecedor"):
        return entries.create(s, eid, EntryData(kind=kind, description=f"{kind} {amount}", amount=D(amount),
                                                due_date=due, account_id=bank, contact=contact))

    late = bill("expense", "1000", date(2026, 7, 20))
    entries.pay(s, late, date(2026, 7, 25), amount=D("1050"))          # 5 dias de atraso: R$ 50 de juros
    early = bill("expense", "400", date(2026, 8, 10))
    entries.pay(s, early, date(2026, 8, 5), amount=D("380"))           # pagou antes com desconto
    got = bill("income", "2000", date(2026, 8, 1), "Cliente")
    entries.pay(s, got, date(2026, 8, 3), amount=D("2020"))            # cliente pagou multa
    gave = bill("income", "500", date(2026, 8, 15), "Cliente")
    entries.pay(s, gave, date(2026, 8, 15), amount=D("450"))           # desconto que você deu
    same = bill("expense", "100", date(2026, 8, 20))
    entries.pay(s, same, date(2026, 8, 20))                            # igual ao previsto: fora
    outside = bill("expense", "100", date(2026, 12, 1))
    entries.pay(s, outside, date(2026, 12, 2), amount=D("110"))        # pago fora do período

    rep = reports.interest_discounts(s, eid, date(2026, 7, 1), date(2026, 8, 31))
    assert [(r.description, r.original, r.amount, r.difference, r.days_late) for r in rep.rows] == [
        ("expense 1000", D("1000.00"), D("1050.00"), D("50.00"), 5),
        ("income 2000", D("2000.00"), D("2020.00"), D("20.00"), 2),
        ("expense 400", D("400.00"), D("380.00"), D("-20.00"), -5),
        ("income 500", D("500.00"), D("450.00"), D("-50.00"), 0)]
    assert (rep.interest_paid, rep.discounts_obtained, rep.interest_received, rep.discounts_given) == \
        (D("50.00"), D("20.00"), D("20.00"), D("50.00"))
    only_paid = reports.interest_discounts(s, eid, date(2026, 7, 1), date(2026, 8, 31), "expense")
    assert [r.kind for r in only_paid.rows] == ["expense", "expense"] and only_paid.interest_received == D("0")
