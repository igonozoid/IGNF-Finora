from datetime import date
from decimal import Decimal as D

import pytest

from finora.models import Attachment, BankLine, Contact, Entry
from finora.services import (
    accounts, attachments, categories, contacts, cost_centers, entity_admin, entries, entry_move, period_lock,
)
from finora.services.entries import EntryData


@pytest.fixture
def two(session, profile, plus):
    s, a = session, profile.id
    b = entity_admin.create(s, name="Padaria Sol", person_type="PJ", dre_model="personal")
    bank_a = accounts.list_accounts(s, a)[0].id
    bank_b = accounts.list_accounts(s, b)[0].id
    luz = dict((label, cid) for cid, label in categories.choices(s, a, "expense"))["Moradia › Luz"]
    return dict(s=s, a=a, b=b, bank_a=bank_a, bank_b=bank_b, luz=luz)


def _new(c, **kw):
    base = dict(kind="expense", description="Conta de luz", amount=D("120.50"), due_date=date(2026, 10, 10),
                account_id=c["bank_a"], category_id=c["luz"], contact="Enel")
    base.update(kw)
    return entries.create(c["s"], c["a"], EntryData(**base))


def test_leva_lancamento_com_categoria_contato_e_anexo(two, tmp_path):
    s = two["s"]
    cc = cost_centers.create(s, two["a"], "Casa")
    (i,) = _new(two, cost_center_id=cc, document_no="FAT-10", notes="Pago no app")
    pdf = tmp_path / "conta.pdf"
    pdf.write_bytes(b"%PDF-1.4 conta")
    attachments.add(s, i, pdf)
    r = entry_move.move_to_entity(s, [i], two["b"], two["bank_b"])
    assert (r.moved, r.categories_cleared, r.cost_centers_cleared) == (1, 0, 1)
    e = s.get(Entry, i)
    assert e.entity_id == two["b"] and e.account_id == two["bank_b"] and e.cost_center_id is None
    assert e.document_no == "FAT-10" and e.notes == "Pago no app" and e.amount == D("120.50")
    cat = entries.get(s, i).category
    assert cat == "Luz" and e.category_id != two["luz"]                       # a "Luz" da entidade de destino
    enel_b = s.get(Contact, e.contact_id)
    assert enel_b.name == "Enel" and enel_b.entity_id == two["b"] and enel_b.is_supplier
    assert [c.name for c in contacts.list_contacts(s, two["a"])] == ["Enel"]  # o da origem continua lá
    assert s.query(Attachment).filter_by(entry_id=i).one().entity_id == two["b"]
    assert entries.list_entries(s, two["a"], year=2026, month=10) == []       # sumiu da origem
    assert [x.id for x in entries.list_entries(s, two["b"], year=2026, month=10)] == [i]
    saldos_b = {a.id: a.balance for a in accounts.list_accounts(s, two["b"])}
    assert saldos_b[two["bank_b"]] == D("0")                                   # em aberto: não mexe no saldo


def test_categoria_sem_par_fica_em_branco_e_serie_vai_junto(two):
    s = two["s"]
    g = categories.create(s, two["a"], name="Apiário", dre_group="outras")
    ids = _new(two, category_id=g, repeat="monthly", times=3)
    r = entry_move.move_to_entity(s, ids[1:], two["b"], two["bank_b"])
    assert r.moved == 2 and r.categories_cleared == 2
    moved = [s.get(Entry, i) for i in ids[1:]]
    assert all(e.category_id is None for e in moved)
    assert len({e.series_id for e in moved}) == 1 and moved[0].series_id != s.get(Entry, ids[0]).series_id
    assert entries.in_series(s, ids[0]) == 0                                    # a série da origem não puxa o destino


def test_solta_a_conciliacao_da_origem(two):
    s = two["s"]
    (i,) = _new(two)
    s.add(BankLine(entity_id=two["a"], account_id=two["bank_a"], fitid="X1", posted=date(2026, 10, 10),
                   amount=D("-120.50"), memo="ENEL", status="matched", entry_id=i))
    s.commit()
    entry_move.move_to_entity(s, [i], two["b"], two["bank_b"])
    line = s.query(BankLine).filter_by(fitid="X1").one()
    assert line.entry_id is None and line.status == "pending"


def test_regras(two):
    s = two["s"]
    (t,) = _new(two, kind="transfer", description="Saque", category_id=None, contact=None,
                dest_account_id=accounts.create(s, two["a"], name="Carteira", kind="cash", opening_balance=D(0)))
    with pytest.raises(ValueError, match="transferência"):
        entry_move.move_to_entity(s, [t], two["b"], two["bank_b"])
    (i,) = _new(two)
    with pytest.raises(ValueError, match="outra entidade"):
        entry_move.move_to_entity(s, [i], two["a"], two["bank_a"])                 # mesma entidade
    with pytest.raises(ValueError, match="conta ativa"):
        entry_move.move_to_entity(s, [i], two["b"], two["bank_a"])                 # conta da origem
    usd = accounts.create(s, two["b"], name="Conta EUA", kind="bank", opening_balance=D(0), currency="USD")
    with pytest.raises(ValueError, match="outra moeda"):
        entry_move.move_to_entity(s, [i], two["b"], usd)
    card = accounts.create(s, two["b"], name="Visa", kind="card", opening_balance=D(0), closing_day=25, due_day=5)
    with pytest.raises(ValueError, match="cartão"):
        entry_move.move_to_entity(s, [i], two["b"], card)
    period_lock.set_lock(s, two["b"], date(2026, 9, 30))
    (old,) = _new(two, due_date=date(2026, 9, 10))
    with pytest.raises(period_lock.PeriodLockedError, match="Padaria Sol"):        # fechado no destino
        entry_move.move_to_entity(s, [old], two["b"], two["bank_b"])
    assert s.get(Entry, i).entity_id == two["a"] and s.get(Entry, old).entity_id == two["a"]
    assert [d[1] for d in entry_move.destinations(s, two["a"])] == ["Padaria Sol"]
    assert [a[1] for a in entry_move.destinations(s, two["a"])[0][2]] == ["Conta principal", "Conta EUA"]   # sem o cartão


def test_sem_acesso_total_no_destino(two, monkeypatch):
    from finora.core.current import current
    from finora.services import permissions, users
    s = two["s"]
    uid = users.create(s, name="Bia", email="bia@exemplo.test", password="segredo123", is_admin=False,
                       entity_ids=[two["a"], two["b"]])
    permissions.set_level(s, uid, two["b"], "financial", "read")
    monkeypatch.setattr(current, "user_id", uid)
    (i,) = _new(two)
    with pytest.raises(permissions.AccessDenied, match="Padaria Sol"):
        entry_move.move_to_entity(s, [i], two["b"], two["bank_b"])
    assert entry_move.destinations(s, two["a"]) == []
