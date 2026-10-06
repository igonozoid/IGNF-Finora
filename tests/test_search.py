from datetime import date
from decimal import Decimal as D

from finora.services import accounts, contacts, entries, search
from finora.services.entries import EntryData


def test_busca_global(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    contacts.create(s, eid, name="Enel Distribuição", person_type="PJ", document="11222333000181")
    entries.create(s, eid, EntryData(kind="expense", description="Conta de luz", amount=D("180"),
                                     due_date=date(2025, 3, 10), account_id=bank, contact="Enel Distribuição"))
    entries.create(s, eid, EntryData(kind="expense", description="Luz de natal", amount=D("40"),
                                     due_date=date(2026, 12, 1), account_id=bank))
    assert search.search(s, eid, "l") == []                              # mínimo de 2 letras
    hits = search.search(s, eid, "luz")
    kinds = [(h.kind, h.title) for h in hits]
    assert ("category", "Luz") in kinds                                   # categoria padrão
    entries_found = [h.title for h in hits if h.kind == "entry"]
    assert entries_found == ["Luz de natal", "Conta de luz"]               # de qualquer mês, mais novo primeiro
    by_contact = [h.title for h in search.search(s, eid, "enel") if h.kind == "entry"]
    assert by_contact == ["Conta de luz"]                                 # acha pelo nome do contato
    assert [h.kind for h in search.search(s, eid, "11.222.333")] == ["contact"]   # pelo CNPJ
    assert [(h.kind, h.title) for h in search.search(s, eid, "banco")] == [("account", "Banco")]
    sub = next(h for h in hits if h.kind == "entry" and h.title == "Conta de luz").subtitle
    assert "10/03/2025" in sub and "Enel" in sub and "R$ 180,00" in sub
