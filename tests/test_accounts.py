from datetime import date
from decimal import Decimal as D

import pytest

from finora.models import Entry
from finora.services import accounts


def _entry(s, entity_id, kind, account_id, amount, status="paid", dest=None):
    s.add(Entry(entity_id=entity_id, kind=kind, account_id=account_id, dest_account_id=dest, amount=D(amount),
                competence_date=date(2026, 10, 1), due_date=date(2026, 10, 1), status=status))
    s.commit()


def test_criar_e_listar(session, profile):
    acc_id = accounts.create(session, profile.id, name="Carteira", kind="cash", opening_balance=D("20"))
    lst = accounts.list_accounts(session, profile.id)
    assert [a.name for a in lst] == ["Banco", "Carteira"]
    assert next(a for a in lst if a.id == acc_id).currency == "BRL"
    assert accounts.total_balance(lst) == D("120.00")


def test_nome_repetido(session, profile):
    with pytest.raises(ValueError):
        accounts.create(session, profile.id, name=" banco ", kind="cash", opening_balance=D(0))


def test_cartao_fica_negativo(session, profile):
    acc_id = accounts.create(session, profile.id, name="Cartão", kind="card", opening_balance=D("300"))
    assert next(a for a in accounts.list_accounts(session, profile.id) if a.id == acc_id).balance == D("-300")


def test_saldo_com_lancamentos(session, profile):
    banco = accounts.list_accounts(session, profile.id)[0].id
    cart = accounts.create(session, profile.id, name="Carteira", kind="cash", opening_balance=D(0))
    _entry(session, profile.id, "income", banco, "50")
    _entry(session, profile.id, "expense", banco, "30")
    _entry(session, profile.id, "expense", banco, "999", status="pending")  # não pago: não conta
    _entry(session, profile.id, "transfer", banco, "40", dest=cart)
    saldos = {a.id: a.balance for a in accounts.list_accounts(session, profile.id)}
    assert saldos[banco] == D("80.00")  # 100 + 50 - 30 - 40
    assert saldos[cart] == D("40.00")


def test_limite_free(session, profile):
    lim = accounts.limit()
    assert lim == 3
    for i in range(lim - 1):
        accounts.create(session, profile.id, name=f"C{i}", kind="cash", opening_balance=D(0))
    assert not accounts.can_add(session, profile.id)
    with pytest.raises(accounts.LimitError):
        accounts.create(session, profile.id, name="Extra", kind="cash", opening_balance=D(0))
    # inativar libera vaga; reativar acima do limite é bloqueado
    first = accounts.list_accounts(session, profile.id)[0].id
    accounts.set_active(session, first, False)
    accounts.create(session, profile.id, name="Extra", kind="cash", opening_balance=D(0))
    with pytest.raises(accounts.LimitError):
        accounts.set_active(session, first, True)


def test_inativas_ficam_ocultas(session, profile):
    acc_id = accounts.list_accounts(session, profile.id)[0].id
    accounts.set_active(session, acc_id, False)
    assert accounts.list_accounts(session, profile.id) == []
    assert len(accounts.list_accounts(session, profile.id, include_inactive=True)) == 1


def test_outra_moeda_so_na_pro(session, profile):
    with pytest.raises(accounts.LimitError):
        accounts.create(session, profile.id, name="Wise", kind="bank", opening_balance=D(0), currency="USD")
    acc_id = accounts.create(session, profile.id, name="Wise", kind="bank", opening_balance=D(0), currency="BRL")
    with pytest.raises(accounts.LimitError):
        accounts.update(session, acc_id, name="Wise", kind="bank", opening_balance=D(0), currency="USD")


# ---------- cheque especial (limite da conta no banco) ----------
def test_limite_so_em_banco_e_cartao(session, profile):
    s, eid = session, profile.id
    bank = accounts.create(s, eid, name="Itaú", kind="bank", opening_balance=D("100"), credit_limit=D("500"))
    cash = accounts.create(s, eid, name="Carteira", kind="cash", opening_balance=D("0"), credit_limit=D("500"))
    views = {a.id: a for a in accounts.list_accounts(s, eid)}
    assert views[bank].credit_limit == D("500") and views[cash].credit_limit is None    # carteira não tem
    with pytest.raises(ValueError, match="negativo"):
        accounts.update(s, bank, name="Itaú", kind="bank", opening_balance=D("100"), credit_limit=D("-1"))
    accounts.update(s, bank, name="Itaú", kind="bank", opening_balance=D("100"), credit_limit=None)
    assert accounts.limit_checks(s, eid) == {}                                          # sem limite, sem checagem


def test_aviso_quando_o_saldo_previsto_passa_do_limite(session, profile):
    from finora.services import entries
    from finora.services.entries import EntryData
    s, eid = session, profile.id
    today = date(2026, 10, 15)
    bank = accounts.create(s, eid, name="Itaú", kind="bank", opening_balance=D("100"), credit_limit=D("500"))

    def add(kind, amount, due):
        entries.create(s, eid, EntryData(kind=kind, description=kind, amount=D(amount), due_date=due,
                                         account_id=bank))
    c = accounts.limit_checks(s, eid, today)[bank]
    assert (c.balance, c.available, c.over_now, c.over_soon) == (D("100"), D("600"), False, False)
    add("expense", "400", date(2026, 10, 10))          # atrasada: conta como hoje -> -300
    add("expense", "350", date(2026, 10, 20))          # -> -650: passa do limite de 500 no dia 20
    add("income", "1000", date(2026, 10, 25))          # volta a +350
    add("expense", "5000", date(2026, 12, 1))          # fora dos 30 dias: não entra
    c = accounts.limit_checks(s, eid, today)[bank]
    assert c.lowest == D("-650") and c.lowest_day == date(2026, 10, 20)
    assert c.over_soon and not c.over_now
    _entry(s, eid, "expense", bank, "700")            # paga: saldo de hoje -600 (já passou)
    c = accounts.limit_checks(s, eid, today)[bank]
    assert c.balance == D("-600") and c.over_now and c.available == D("-100")
