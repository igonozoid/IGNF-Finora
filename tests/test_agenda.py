"""Agenda (módulo "agenda", decisão D4)."""
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from finora.models import Task
from finora.services import accounts, agenda, contacts, modules, reminders
from finora.services.entries import EntryData, create


@pytest.mark.parametrize("due, rec, day, nxt", [
    (date(2026, 1, 31), "daily", None, date(2026, 2, 1)),
    (date(2026, 1, 31), "weekly", None, date(2026, 2, 7)),
    (date(2026, 1, 31), "fortnightly", None, date(2026, 2, 14)),
    (date(2026, 1, 31), "monthly", None, date(2026, 2, 28)),            # 31 vira o último dia
    (date(2026, 2, 28), "monthly", 31, date(2026, 3, 31)),              # dia fixo volta ao 31
    (date(2026, 11, 10), "quarterly", None, date(2027, 2, 10)),
    (date(2026, 3, 5), "yearly", None, date(2027, 3, 5)),
    (date(2026, 3, 5), "none", None, None),
])
def test_proxima_data(due, rec, day, nxt):
    assert agenda.next_due(due, rec, day) == nxt


def test_salvar_listar_e_filtrar(session, profile):
    s, eid = session, profile.id
    today = date(2026, 10, 23)
    a = agenda.save(s, eid, title="Pagar IPVA", due_date=date(2026, 10, 20), contact="Detran")
    agenda.save(s, eid, title="Ligar para a Enel", due_date=date(2026, 10, 25))
    agenda.save(s, eid, title="Sem data")
    assert [t.title for t in agenda.list_tasks(s, eid, today=today)] == ["Pagar IPVA", "Ligar para a Enel",
                                                                          "Sem data"]
    assert [t.title for t in agenda.list_tasks(s, eid, "late", today=today)] == ["Pagar IPVA"]
    assert [t.title for t in agenda.list_tasks(s, eid, search="detran")] == ["Pagar IPVA"]
    assert agenda.counts(s, eid, today) == {"open": 3, "late": 1, "done": 0, "all": 3}
    assert agenda.list_tasks(s, eid)[0].contact == "Detran"
    assert contacts.list_contacts(s, eid, role="review")[0].name == "Detran"     # criado pela tarefa
    agenda.save(s, eid, a, title="Pagar IPVA 2026", due_date=date(2026, 10, 20))
    assert agenda.list_tasks(s, eid, search="2026")[0].contact == ""


def test_validacoes(session, profile):
    with pytest.raises(ValueError, match="precisa ser feito"):
        agenda.save(session, profile.id, title=" ")
    with pytest.raises(ValueError, match="precisa de data"):
        agenda.save(session, profile.id, title="X", recurrence="monthly")
    with pytest.raises(ValueError, match="Dia do mês"):
        agenda.save(session, profile.id, title="X", due_date=date(2026, 1, 1), recurrence="monthly",
                    recurrence_day=40)


def test_concluir_recorrente_cria_a_proxima_uma_vez(session, profile):
    s, eid = session, profile.id
    tid = agenda.save(s, eid, title="Aluguel", due_date=date(2026, 10, 10), recurrence="monthly", recurrence_day=10)
    nxt = agenda.complete(s, tid, datetime(2026, 10, 10, 9))
    t = s.get(Task, nxt)
    assert (t.due_date, t.status, t.recurrence_day) == (date(2026, 11, 10), "pending", 10)
    agenda.reopen(s, tid)
    assert agenda.complete(s, tid) is None                         # a de novembro já existe: não duplica
    assert agenda.complete(s, agenda.save(s, eid, title="Única", due_date=date(2026, 10, 1))) is None
    agenda.delete(s, nxt)
    assert s.get(Task, nxt) is None


def test_ligar_a_um_lancamento(session, profile):
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    e = create(s, eid, EntryData(kind="expense", description="Luz", amount=D("90"), due_date=date(2026, 11, 5),
                                 account_id=bank))[0]
    assert (e, "05/11/2026 · Luz") in agenda.entry_choices(s, eid)
    agenda.save(s, eid, title="Conferir a conta", entry_id=e)
    assert agenda.list_tasks(s, eid)[0].entry_label == "Luz — 05/11/2026"
    with pytest.raises(ValueError, match="Lançamento"):
        agenda.save(s, eid, title="X", entry_id=9999)


def test_calendario_e_lembretes(session, profile):
    s, eid = session, profile.id
    contacts.create(s, eid, name="Maria", details={"birthday": "24/10/1980"})
    agenda.save(s, eid, title="Reunião", due_date=date(2026, 10, 23))
    items = agenda.occurrences(s, eid, date(2026, 10, 1), date(2026, 10, 31))
    assert [(i.day.day, i.kind, i.text) for i in items] == [(23, "task", "Reunião"),
                                                            (24, "birthday", "Aniversário de Maria")]
    today = date(2026, 10, 23)
    assert "Tarefa: Reunião (hoje)" not in reminders.check(s, eid, 1, today).dates     # módulo desligado
    modules.set_enabled(s, eid, "agenda", True)
    r = reminders.check(s, eid, 1, today)
    assert r.dates == ["Aniversário de Maria (amanhã)", "Tarefa: Reunião (hoje)"]


def test_mesclar_contato_leva_as_tarefas(session, profile):
    s, eid = session, profile.id
    keep = contacts.create(s, eid, name="Enel")
    drop = contacts.create(s, eid, name="ENEL SA")
    tid = agenda.save(s, eid, title="Ligar", contact="ENEL SA")
    contacts.merge(s, keep, drop)
    assert s.get(Task, tid).contact_id == keep
