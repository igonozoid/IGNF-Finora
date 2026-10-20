"""Analítico com agrupamentos livres (Fase 3.9, relatório do MCC)."""
from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, entries, reports
from finora.services.entries import EntryData


def _data(s, eid):
    bank = accounts.list_accounts(s, eid)[0].id

    def add(kind, amount, month, contact=None, paid=False):
        entries.create(s, eid, EntryData(kind=kind, description=f"{kind} {month}", amount=D(amount),
                                         due_date=date(2026, month, 10), account_id=bank, contact=contact,
                                         paid=paid, paid_date=date(2026, month, 10) if paid else None))

    add("income", "1000", 1, "Maria", paid=True)
    add("expense", "200", 1, "Enel", paid=True)
    add("expense", "300", 2, "Enel")
    add("income", "500", 2, "Maria")
    add("expense", "50", 2)                                             # sem contato
    return reports.analytical(s, eid, date(2026, 1, 1), date(2026, 12, 31))


def test_um_nivel(session, profile):
    data = _data(session, profile.id)
    by_contact = reports.analytical_grouped(data, "contact")
    assert [(g.label, g.count, g.income, g.expense, g.result) for g in by_contact] == [
        ("Enel", 2, D("0"), D("500.00"), D("-500.00")),
        ("Maria", 2, D("1500.00"), D("0"), D("1500.00")),
        ("Sem contato", 1, D("0"), D("50.00"), D("-50.00"))]          # "Sem …" no fim
    assert [e.description for e in by_contact[0].entries] == ["expense 1", "expense 2"]   # na ordem das datas
    by_month = reports.analytical_grouped(data, "month")
    assert [(g.label, g.result) for g in by_month] == [("jan/2026", D("800.00")), ("fev/2026", D("150.00"))]
    assert [g.label for g in reports.analytical_grouped(data, "kind")] == ["Receitas", "Despesas"]
    assert [g.label for g in reports.analytical_grouped(data, "status")] == ["Pago ou recebido", "Em aberto"]


def test_dois_niveis_na_ordem_escolhida(session, profile):
    data = _data(session, profile.id)
    groups = reports.analytical_grouped(data, "month", "contact")
    feb = groups[1]
    assert (feb.label, feb.count, feb.level) == ("fev/2026", 3, 1) and feb.entries == []
    assert [(c.label, c.level, c.count, c.result) for c in feb.children] == [
        ("Enel", 2, 1, D("-300.00")), ("Maria", 2, 1, D("500.00")), ("Sem contato", 2, 1, D("-50.00"))]
    other = reports.analytical_grouped(data, "contact", "month")       # a ordem inverte a árvore
    assert [c.label for c in other[0].children] == ["jan/2026", "fev/2026"]
    total = sum((g.result for g in groups), D(0))
    assert total == sum((e.base_amount if e.kind == "income" else -e.base_amount for e in data), D(0))


def test_agrupamento_invalido(session, profile):
    data = _data(session, profile.id)
    for args in (("cidade",), ("contact", "contact"), (None,)):
        with pytest.raises(ValueError):
            reports.analytical_grouped(data, *args)
