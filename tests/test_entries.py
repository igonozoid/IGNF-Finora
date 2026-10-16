from datetime import date
from decimal import Decimal as D

import pytest

from finora.services import accounts, categories, contacts, entries
from finora.services.entries import EntryData

TODAY = date(2026, 10, 15)


@pytest.fixture
def ctx(session, profile):
    bank = accounts.list_accounts(session, profile.id)[0].id
    cash = accounts.create(session, profile.id, name="Carteira", kind="cash", opening_balance=D(0))
    cats = dict((label, cid) for cid, label in categories.choices(session, profile.id, "expense"))
    incs = dict((label, cid) for cid, label in categories.choices(session, profile.id, "income"))
    return dict(s=session, eid=profile.id, bank=bank, cash=cash,
                luz=cats["Moradia › Luz"], mercado=cats["Alimentação › Supermercado"], salario=incs["Receitas › Salário"])


def _data(c, **kw):
    base = dict(kind="expense", description="Conta de luz", amount=D("120.50"), due_date=date(2026, 10, 10),
                account_id=c["bank"], category_id=c["luz"])
    base.update(kw)
    return EntryData(**base)


def _list(c, filter="all", year=2026, month=10, search=""):
    return entries.list_entries(c["s"], c["eid"], year=year, month=month, filter=filter, search=search, today=TODAY)


# ---------- utilitários ----------
def test_add_months_respeita_fim_do_mes():
    assert entries.occurrence(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)
    assert entries.occurrence(date(2026, 1, 31), "monthly", 2) == date(2026, 3, 31)
    assert entries.occurrence(date(2026, 12, 15), "monthly", 1) == date(2027, 1, 15)
    assert entries.occurrence(date(2026, 10, 1), "weekly", 2) == date(2026, 10, 15)
    assert entries.occurrence(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)


def test_intervalos_do_mcc():
    d = date(2026, 1, 31)
    assert entries.occurrence(d, "daily", 3) == date(2026, 2, 3)
    assert entries.occurrence(date(2026, 10, 1), "biweekly", 3) == date(2026, 11, 15)   # quinzenal = 15 dias
    assert entries.occurrence(d, "bimonthly", 1) == date(2026, 3, 31)
    assert entries.occurrence(d, "bimonthly", 2) == date(2026, 5, 31)
    assert entries.occurrence(d, "quarterly", 1) == date(2026, 4, 30)                # 31/04 não existe
    assert entries.occurrence(d, "semiannual", 1) == date(2026, 7, 31)
    # parcelado usa o intervalo de `every` (padrão: mensal)
    assert entries.occurrence(d, "installments", 1) == date(2026, 2, 28)
    assert entries.occurrence(d, "installments", 2, "biweekly") == date(2026, 3, 2)
    assert set(entries.INTERVALS) <= set(entries.REPEATS)


def test_split_parcelas():
    assert entries.split(D("100.00"), 3) == [D("33.34"), D("33.33"), D("33.33")]
    assert sum(entries.split(D("1000.01"), 7)) == D("1000.01")


# ---------- criação ----------
def test_cria_simples_e_status(ctx):
    entries.create(ctx["s"], ctx["eid"], _data(ctx))
    e = _list(ctx)[0]
    assert e.category == "Luz" and e.account == "Banco" and not e.is_paid
    assert e.status_label(TODAY) == "Atrasado"  # venceu dia 10, hoje é 15
    assert e.status_label(date(2026, 10, 1)) == "A pagar"


def test_validacoes(ctx):
    with pytest.raises(ValueError):
        entries.create(ctx["s"], ctx["eid"], _data(ctx, amount=D(0)))
    with pytest.raises(ValueError):
        entries.create(ctx["s"], ctx["eid"], _data(ctx, description=" "))
    with pytest.raises(ValueError):  # categoria de despesa numa receita
        entries.create(ctx["s"], ctx["eid"], _data(ctx, kind="income"))
    with pytest.raises(ValueError):
        entries.create(ctx["s"], ctx["eid"], _data(ctx, kind="transfer", dest_account_id=ctx["bank"]))
    accounts.set_active(ctx["s"], ctx["cash"], False)
    with pytest.raises(ValueError):  # conta inativa
        entries.create(ctx["s"], ctx["eid"], _data(ctx, account_id=ctx["cash"]))
    assert _list(ctx) == []


def test_parcelado(ctx):
    ids = entries.create(ctx["s"], ctx["eid"], _data(ctx, description="Geladeira", amount=D("1000.00"),
                                                     repeat="installments", times=3, paid=True))
    assert len(ids) == 3
    out = [entries.get(ctx["s"], i) for i in ids]
    assert [e.installment for e in out] == ["1/3", "2/3", "3/3"]
    assert [e.amount for e in out] == [D("333.34"), D("333.33"), D("333.33")]
    assert [e.due_date for e in out] == [date(2026, 10, 10), date(2026, 11, 10), date(2026, 12, 10)]
    assert [e.is_paid for e in out] == [True, False, False]  # só a 1ª nasce paga
    assert len({e.series_id for e in out}) == 1 and not out[0].is_recurring


def test_parcelado_quinzenal_como_no_mcc(ctx):
    ids = entries.create(ctx["s"], ctx["eid"], _data(ctx, description="Conserto do trator", amount=D("1000.00"),
                                                     due_date=date(2026, 10, 1), repeat="installments",
                                                     every="biweekly", times=4))
    out = [entries.get(ctx["s"], i) for i in ids]
    assert [e.due_date for e in out] == [date(2026, 10, 1), date(2026, 10, 16), date(2026, 10, 31),
                                         date(2026, 11, 15)]            # mesmas datas do lançamento do MCC
    assert [e.installment for e in out] == ["1/4", "2/4", "3/4", "4/4"]
    assert sum(e.amount for e in out) == D("1000.00")
    with pytest.raises(ValueError, match="Intervalo das parcelas"):
        entries.create(ctx["s"], ctx["eid"], _data(ctx, repeat="installments", every="hourly", times=2))


def test_documento_da_parcela_ganha_n_de_n():
    assert entries.installment_doc("NF-4521", "2/3") == "NF-4521 2/3"
    assert entries.installment_doc("NF-4521 1/3", "2/3") == "NF-4521 2/3"        # troca, não repete
    assert entries.installment_doc("  ", "2/3") is None                           # sem documento continua vazio
    assert entries.installment_doc("Boleto 10/2026", None) == "Boleto 10/2026"    # fora do parcelado, intacto


def test_parcelado_documento_e_competencia_na_data_da_compra(ctx):
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, description="Adubo", amount=D("4000.00"), document_no="NF-4521",
                                              due_date=date(2026, 8, 10), repeat="installments", times=3,
                                              competence_first=True))
    out = [entries.get(s, i) for i in ids]
    assert [e.document_no for e in out] == ["NF-4521 1/3", "NF-4521 2/3", "NF-4521 3/3"]
    assert [e.due_date for e in out] == [date(2026, 8, 10), date(2026, 9, 10), date(2026, 10, 10)]
    assert {e.competence_date for e in out} == {date(2026, 8, 10)}                # todas na data da compra
    # padrão (como era antes): cada parcela conta no mês em que vence
    ids2 = entries.create(s, ctx["eid"], _data(ctx, description="Geladeira", amount=D("900"), repeat="installments",
                                               times=3))
    assert [entries.get(s, i).competence_date for i in ids2] == [date(2026, 10, 10), date(2026, 11, 10),
                                                                  date(2026, 12, 10)]
    # competence_first só vale no parcelado
    (one,) = entries.create(s, ctx["eid"], _data(ctx, competence_first=True))
    assert entries.get(s, one).competence_date == entries.get(s, one).due_date


def test_editar_parcelas_mantem_competencia_e_sufixo(ctx):
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, description="Adubo", amount=D("3000.00"), document_no="NF-1",
                                              due_date=date(2026, 8, 10), repeat="installments", times=3,
                                              competence_first=True))
    # edita a 2ª parcela "e as próximas": muda o documento e o vencimento da 2ª
    entries.update(s, ids[1], _data(ctx, description="Adubo orgânico", amount=D("1000.00"), document_no="NF-2 2/3",
                                    due_date=date(2026, 9, 15)), scope="following")
    out = [entries.get(s, i) for i in ids]
    assert [e.document_no for e in out] == ["NF-1 1/3", "NF-2 2/3", "NF-2 3/3"]
    assert [e.due_date for e in out] == [date(2026, 8, 10), date(2026, 9, 15), date(2026, 10, 10)]
    assert {e.competence_date for e in out} == {date(2026, 8, 10)}                # competência não andou
    assert [e.description for e in out] == ["Adubo", "Adubo orgânico", "Adubo orgânico"]


def test_dre_por_competencia_respeita_a_data_da_compra(ctx):
    from finora.services import reports
    s, eid = ctx["s"], ctx["eid"]
    entries.create(s, eid, _data(ctx, description="TV", amount=D("3000.00"), due_date=date(2026, 8, 10),
                                 repeat="installments", times=3, competence_first=True))
    aug = reports.analytical(s, eid, date(2026, 8, 1), date(2026, 8, 31))
    sep = reports.analytical(s, eid, date(2026, 9, 1), date(2026, 9, 30))
    assert sum(e.amount for e in aug if e.description == "TV") == D("3000.00")   # a compra inteira em agosto
    assert [e for e in sep if e.description == "TV"] == []
    dre_aug = reports.dre(s, eid, [(2026, 8)])
    assert sum(r.values[0] for r in dre_aug.rows if r.style == "line") == D("-3000.00")


def test_repete_a_cada_2_3_e_6_meses(ctx):
    s = ctx["s"]
    for rep, last in (("bimonthly", date(2027, 4, 10)), ("quarterly", date(2027, 7, 10)),
                      ("semiannual", date(2028, 4, 10))):
        ids = entries.create(s, ctx["eid"], _data(ctx, description=rep, repeat=rep, times=4))
        out = [entries.get(s, i) for i in ids]
        assert out[-1].due_date == last and all(e.amount == D("120.50") and e.is_recurring for e in out)


def test_recorrente(ctx):
    ids = entries.create(ctx["s"], ctx["eid"], _data(ctx, repeat="monthly", times=12))
    out = [entries.get(ctx["s"], i) for i in ids]
    assert all(e.amount == D("120.50") and e.is_recurring and e.installment is None for e in out)
    assert out[-1].due_date == date(2027, 9, 10)


def test_transferencia_move_saldo(ctx):
    entries.create(ctx["s"], ctx["eid"], _data(ctx, kind="transfer", description="Saque", amount=D("40"),
                                               category_id=ctx["luz"], contact="Ignorado",
                                               dest_account_id=ctx["cash"], paid=True))
    e = _list(ctx)[0]
    assert e.category is None and e.contact is None and e.dest_account == "Carteira"
    saldos = {a.id: a.balance for a in accounts.list_accounts(ctx["s"], ctx["eid"])}
    assert saldos[ctx["bank"]] == D("60.00") and saldos[ctx["cash"]] == D("40.00")


def test_contato_criado_pelo_nome(ctx):
    entries.create(ctx["s"], ctx["eid"], _data(ctx, contact="Enel"))
    entries.create(ctx["s"], ctx["eid"], _data(ctx, contact=" enel "))
    assert contacts.names(ctx["s"], ctx["eid"]) == ["Enel"]


# ---------- filtros e totais ----------
def test_filtros(ctx):
    s, eid = ctx["s"], ctx["eid"]
    entries.create(s, eid, _data(ctx))                                                     # atrasada
    entries.create(s, eid, _data(ctx, description="Mercado", category_id=ctx["mercado"], due_date=date(2026, 10, 20)))
    entries.create(s, eid, _data(ctx, kind="income", description="Salário", amount=D("5000"),
                                 category_id=ctx["salario"], due_date=date(2026, 10, 5), paid=True,
                                 paid_date=date(2026, 10, 5)))
    entries.create(s, eid, _data(ctx, description="Luz setembro", due_date=date(2026, 9, 10)))  # atrasada, outro mês
    names = lambda f, **kw: [e.description for e in _list(ctx, f, **kw)]
    assert names("all") == ["Salário", "Conta de luz", "Mercado"]
    assert names("payable") == ["Conta de luz", "Mercado"]
    assert names("receivable") == []
    assert names("late") == ["Luz setembro", "Conta de luz"]  # atrasados de qualquer mês
    assert names("paid") == ["Salário"]
    assert names("all", search="merc") == ["Mercado"]
    t = entries.month_totals(s, eid, 2026, 10)
    assert t.payable == D("241.00") and t.receivable == D("0.00") and t.balance == D("-241.00")


# ---------- edição e exclusão ----------
def test_editar_este_e_proximos(ctx):
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, repeat="monthly", times=4))
    entries.set_paid(s, ids[2], True, date(2026, 12, 10))
    n = entries.update(s, ids[1], _data(ctx, description="Luz (nova tarifa)", amount=D("150"),
                                        due_date=date(2026, 11, 12)), scope="following")
    assert n == 2  # o 2º e o 4º; o 3º já está pago
    out = [entries.get(s, i) for i in ids]
    assert [e.amount for e in out] == [D("120.50"), D("150"), D("120.50"), D("150")]
    assert out[1].due_date == date(2026, 11, 12) and out[3].due_date == date(2027, 1, 10)


def test_editar_so_este(ctx):
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, repeat="monthly", times=3))
    assert entries.in_series(s, ids[0]) == 2
    entries.update(s, ids[0], _data(ctx, amount=D("99")))
    assert [entries.get(s, i).amount for i in ids] == [D("99"), D("120.50"), D("120.50")]


def test_excluir_este_e_proximos(ctx):
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, repeat="monthly", times=4))
    assert entries.delete(s, ids[1], scope="following") == ids[1:]
    assert [e.id for e in _list(ctx)] == [ids[0]]


def _serie(ctx, n=5):
    """Série mensal com a 1ª e a 3ª pagas (out, nov, dez, jan, fev)."""
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, repeat="monthly", times=n))
    entries.set_paid(s, ids[0], True, date(2026, 10, 10))
    entries.set_paid(s, ids[2], True, date(2026, 12, 10))
    return ids


def test_info_da_serie(ctx):
    ids = _serie(ctx)
    info = entries.series_info(ctx["s"], ids[1])
    assert (info.total, info.open, info.following_open) == (5, 3, 2)
    (avulso,) = entries.create(ctx["s"], ctx["eid"], _data(ctx))
    assert entries.series_info(ctx["s"], avulso).total == 1


def test_excluir_todos_em_aberto_da_serie(ctx):
    s = ctx["s"]
    ids = _serie(ctx)
    gone = entries.delete(s, ids[3], scope="open")                 # inclui o em aberto ANTES deste (o 2º)
    assert gone == [ids[1], ids[3], ids[4]]
    left = [e.id for e in entries.list_entries(s, ctx["eid"], year=2026, month=10, period="all", today=TODAY)]
    assert left == [ids[0], ids[2]]                                  # os pagos ficam


def test_excluir_a_serie_toda_e_restaurar(ctx):
    from finora.services import trash
    s = ctx["s"]
    ids = _serie(ctx)
    gone = entries.delete(s, ids[2], scope="all")                  # pagos inclusive
    assert gone == ids
    assert entries.list_entries(s, ctx["eid"], year=2026, month=10, period="all", today=TODAY) == []
    assert trash.restore(s, gone) == 5
    with pytest.raises(ValueError, match="inválida"):
        entries.delete(s, ids[0], scope="tudo")


def test_excluir_serie_respeita_fechamento(ctx):
    from finora.services import period_lock
    s = ctx["s"]
    ids = entries.create(s, ctx["eid"], _data(ctx, due_date=date(2026, 8, 10), repeat="monthly", times=3))
    period_lock.set_lock(s, ctx["eid"], date(2026, 8, 31))
    with pytest.raises(period_lock.PeriodLockedError):            # agosto está fechado: nada é excluído
        entries.delete(s, ids[1], scope="all")
    assert len(entries.list_entries(s, ctx["eid"], year=2026, month=10, period="all", today=TODAY)) == 3
    assert entries.delete(s, ids[1], scope="following") == ids[1:]    # setembro em diante: pode


def test_lixeira_some_de_tudo_e_volta(ctx):
    from sqlalchemy import func, select

    from finora.models import Entry
    from finora.services import accounts, audit, trash
    s, eid = ctx["s"], ctx["eid"]
    ids = entries.create(s, eid, _data(ctx, repeat="monthly", times=2, paid=True, paid_date=date(2026, 10, 5)))
    bal = accounts.list_accounts(s, eid)[0].balance
    gone = entries.delete(s, ids[0])
    assert gone == [ids[0]] and s.get(Entry, ids[0]) is None
    assert accounts.list_accounts(s, eid)[0].balance != bal                  # saldo sem ele
    assert s.scalar(select(func.count(Entry.id)).where(Entry.id == ids[0])) == 0   # nem contagem enxerga
    still = trash.get(s, ids[0])
    assert still is not None and still.deleted_at is not None              # continua no banco
    items = trash.list_trash(s, eid)
    assert [t.id for t in items] == [ids[0]] and trash.count(s, eid) == 1
    assert trash.restore(s, gone) == 1 and entries.get(s, ids[0]) is not None
    assert accounts.list_accounts(s, eid)[0].balance == bal and trash.count(s, eid) == 0
    texts = [a.summary for a in audit.list_log(s, eid)]
    assert texts[0].startswith("Restaurou da lixeira") and texts[1].startswith("Mandou para a lixeira")


def test_marcar_pago(ctx):
    s = ctx["s"]
    (i,) = entries.create(s, ctx["eid"], _data(ctx))
    entries.set_paid(s, i, True, date(2026, 10, 11))
    e = entries.get(s, i)
    assert e.is_paid and e.paid_date == date(2026, 10, 11) and e.status_label(TODAY) == "Pago"
    assert accounts.list_accounts(s, ctx["eid"])[0].balance == D("-20.50")
    entries.set_paid(s, i, False)
    assert not entries.get(s, i).is_paid


def test_baixa_com_juros_outra_conta_e_observacao(ctx):
    s, eid = ctx["s"], ctx["eid"]
    (i,) = entries.create(s, eid, _data(ctx, amount=D("1000.00"), notes="Manutenção do trator"))
    entries.pay(s, i, date(2026, 10, 15), amount=D("1050.00"), account_id=ctx["cash"],
                note="Pago com 5 dias de atraso")
    e = entries.get(s, i)
    assert e.is_paid and e.paid_date == date(2026, 10, 15) and e.account_id == ctx["cash"]
    assert e.amount == D("1050.00") and e.original_amount == D("1000.00") and e.paid_difference == D("50.00")
    assert e.notes == "Manutenção do trator\nPago com 5 dias de atraso"           # vai para o fim
    saldos = {a.id: a.balance for a in accounts.list_accounts(s, eid)}
    assert saldos[ctx["cash"]] == D("-1050.00") and saldos[ctx["bank"]] == D("100.00")   # saiu do caixa
    with pytest.raises(ValueError, match="já está pago"):
        entries.pay(s, i)
    # voltar para em aberto mantém o valor pago (como o estorno do MCC); pagar de novo mantém o previsto
    entries.set_paid(s, i, False)
    assert entries.get(s, i).amount == D("1050.00") and entries.get(s, i).original_amount == D("1000.00")
    entries.pay(s, i, date(2026, 10, 16), amount=D("1000.00"))
    e = entries.get(s, i)
    assert e.amount == D("1000.00") and e.original_amount is None and e.paid_difference == 0


def test_baixa_com_desconto_e_so_data(ctx):
    s, eid = ctx["s"], ctx["eid"]
    (r,) = entries.create(s, eid, _data(ctx, kind="income", description="Venda", amount=D("500.00"),
                                        category_id=ctx["salario"]))
    entries.pay(s, r, date(2026, 10, 12), amount=D("480.00"))
    assert entries.get(s, r).paid_difference == D("-20.00")                         # desconto concedido
    (x,) = entries.create(s, eid, _data(ctx))
    entries.pay(s, x)                                                               # só a data (hoje)
    e = entries.get(s, x)
    assert e.is_paid and e.paid_date == date.today() and e.original_amount is None and e.notes is None


def test_baixa_regras(ctx):
    s, eid = ctx["s"], ctx["eid"]
    (t,) = entries.create(s, eid, _data(ctx, kind="transfer", description="Saque", category_id=None,
                                        dest_account_id=ctx["cash"]))
    with pytest.raises(ValueError, match="só a data"):
        entries.pay(s, t, amount=D("1"))
    entries.pay(s, t, date(2026, 10, 11), note="feita no caixa eletrônico")
    assert entries.get(s, t).is_paid and entries.get(s, t).notes == "feita no caixa eletrônico"
    (i,) = entries.create(s, eid, _data(ctx))
    with pytest.raises(ValueError, match="maior que zero"):
        entries.pay(s, i, amount=D("0"))
    accounts.set_active(s, ctx["cash"], False)
    with pytest.raises(ValueError, match="conta ativa"):
        entries.pay(s, i, account_id=ctx["cash"])
    card = accounts.create(s, eid, name="Visa", kind="card", opening_balance=D(0), closing_day=25, due_day=5)
    with pytest.raises(ValueError, match="cartão"):
        entries.pay(s, i, account_id=card)
    assert not entries.get(s, i).is_paid                                           # nada mudou


def test_repetir_no_mes_seguinte(ctx):
    s, eid = ctx["s"], ctx["eid"]
    (i,) = entries.create(s, eid, _data(ctx, amount=D("1000.00"), due_date=date(2026, 1, 31), contact="Enel",
                                        document_no="FAT-01", notes="Contrato 5"))
    entries.pay(s, i, date(2026, 2, 3), amount=D("1050.00"))           # pago com juros
    parcelas = entries.create(s, eid, _data(ctx, description="TV", amount=D("300"), document_no="NF-9",
                                            repeat="installments", times=3))
    new = entries.repeat_next_month(s, [i, parcelas[1]])
    a, b = (entries.get(s, x) for x in new)
    assert a.due_date == date(2026, 2, 28) and not a.is_paid                  # 31/01 + 1 mês, em aberto
    assert a.amount == D("1000.00") and a.original_amount is None             # o previsto, sem os juros
    assert (a.description, a.contact, a.category, a.document_no, a.notes) == \
        ("Conta de luz", "Enel", "Luz", "FAT-01", "Contrato 5")
    assert a.series_id is None and a.account_id == ctx["bank"]
    assert b.due_date == date(2026, 12, 10) and b.document_no == "NF-9" and b.installment is None   # avulso
    assert entries.get(s, i).amount == D("1050.00")                           # o original não muda
    accounts.set_active(s, ctx["bank"], False)
    with pytest.raises(ValueError, match="conta inativa"):
        entries.repeat_next_month(s, [i])


def test_filtro_por_conta_e_categoria(ctx):
    s, eid = ctx["s"], ctx["eid"]
    entries.create(s, eid, _data(ctx))                                                        # luz, banco
    entries.create(s, eid, _data(ctx, description="Mercado", category_id=ctx["mercado"], account_id=ctx["cash"]))
    entries.create(s, eid, _data(ctx, kind="transfer", description="Saque", amount=D("50"), category_id=None,
                                 dest_account_id=ctx["cash"]))
    names = lambda **kw: [e.description for e in entries.list_entries(s, eid, year=2026, month=10, today=TODAY, **kw)]
    assert names(account_id=ctx["cash"]) == ["Mercado", "Saque"]                         # transferência entra
    assert names(account_id=ctx["bank"]) == ["Conta de luz", "Saque"]
    assert names(category_id=ctx["mercado"]) == ["Mercado"]
    moradia = next(g.id for g in categories.tree(s, eid) if g.name == "Moradia")
    assert names(category_id=moradia) == ["Conta de luz"]                                # grupo inclui filhas


def test_pagar_varios_de_uma_vez(ctx):
    s = ctx["s"]
    a = entries.create(s, ctx["eid"], _data(ctx))[0]
    b = entries.create(s, ctx["eid"], _data(ctx, description="Água"))[0]
    c = entries.create(s, ctx["eid"], _data(ctx, description="Já paga", paid=True))[0]
    assert entries.set_paid_many(s, [a, b, c], date(2026, 10, 12)) == (2, 1)
    assert all(entries.get(s, i).is_paid for i in (a, b)) and entries.get(s, a).paid_date == date(2026, 10, 12)


def test_filtros_de_periodo_data_tipo_contato_e_centro(session, profile):
    from finora.services import contacts, cost_centers
    s, eid = session, profile.id
    bank = accounts.list_accounts(s, eid)[0].id
    cc = cost_centers.create(s, eid, "Casa")

    def add(kind, desc, when, contact=None, ccid=None, paid=False):
        return entries.create(s, eid, EntryData(kind=kind, description=desc, amount=D("10"), due_date=when,
                                                account_id=bank, contact=contact, cost_center_id=ccid, paid=paid,
                                                paid_date=when if paid else None))[0]
    add("expense", "Jan", date(2026, 1, 10), "Enel", cc)
    add("income", "Fev", date(2026, 2, 10))
    add("expense", "Abr", date(2026, 4, 10), "Enel")
    add("expense", "Out", date(2026, 10, 10), paid=True)
    add("expense", "2025", date(2025, 12, 10))

    def names(**kw):
        return [e.description for e in entries.list_entries(s, eid, year=2026, month=10, **kw)]
    assert names() == ["Out"]                                         # padrão: o mês
    assert names(period="q1") == ["Jan", "Fev"] and names(period="s1") == ["Jan", "Fev", "Abr"]
    assert len(names(period="year")) == 4 and len(names(period="all")) == 5
    assert names(period="year", kind="income") == ["Fev"]
    enel = next(c.id for c in contacts.list_contacts(s, eid) if c.name == "Enel")
    assert names(period="all", contact_id=enel) == ["Jan", "Abr"]
    assert names(period="all", cost_center_id=cc) == ["Jan"]
    assert names(period="year", date_field="paid") == ["Out"]          # pela data do pagamento
    assert entries.period_range(2026, 10, "q4") == (date(2026, 10, 1), date(2026, 12, 31))


# ---------- observações (MCC) ----------
def test_observacoes_gravam_editam_e_limpam(ctx):
    s = ctx["s"]
    (i,) = entries.create(s, ctx["eid"], _data(ctx, notes="  Pago com 5 dias de atraso:\nR$ 50,00 de juros  "))
    assert entries.get(s, i).notes == "Pago com 5 dias de atraso:\nR$ 50,00 de juros"   # mantém a quebra de linha
    entries.update(s, i, _data(ctx, notes="   "))
    assert entries.get(s, i).notes is None                                             # em branco vira vazio
    with pytest.raises(ValueError, match="até 1000 caracteres"):
        entries.update(s, i, _data(ctx, notes="x" * (entries.MAX_NOTES + 1)))


def test_observacoes_na_transferencia_e_na_serie(ctx):
    s = ctx["s"]
    (t,) = entries.create(s, ctx["eid"], _data(ctx, kind="transfer", description="Reforço do caixa",
                                               category_id=None, dest_account_id=ctx["cash"], notes="Pedido do João"))
    assert entries.get(s, t).notes == "Pedido do João"
    ids = entries.create(s, ctx["eid"], _data(ctx, repeat="monthly", times=3, notes="Contrato 123"))
    assert all(entries.get(s, i).notes == "Contrato 123" for i in ids)                 # a série toda nasce com ela
    entries.update(s, ids[1], _data(ctx, notes="Reajuste 2027", due_date=date(2026, 11, 10)), scope="following")
    assert [entries.get(s, i).notes for i in ids] == ["Contrato 123", "Reajuste 2027", "Reajuste 2027"]


def test_busca_encontra_pelas_observacoes(ctx):
    from finora.services import search
    s, eid = ctx["s"], ctx["eid"]
    entries.create(s, eid, _data(ctx, notes="Comprovante na pasta azul"))
    entries.create(s, eid, _data(ctx, description="Água"))
    assert [e.description for e in _list(ctx, search="pasta azul")] == ["Conta de luz"]   # busca da lista
    hits = [h.title for h in search.search(s, eid, "PASTA AZUL") if h.kind == "entry"]   # busca global (Ctrl K)
    assert hits == ["Conta de luz"]


def test_observacoes_vao_para_o_recibo_e_a_auditoria(ctx):
    from finora.services import audit, receipts
    s, eid = ctx["s"], ctx["eid"]
    (i,) = entries.create(s, eid, _data(ctx, contact="Enel", notes="Juros de\n  R$ 5,00"))
    assert receipts.parties(s, i).notes == "Juros de R$ 5,00"                          # recibo: uma linha só
    entries.update(s, i, _data(ctx, contact="Enel", notes="Sem juros"))
    change = next(a for a in audit.list_log(s, eid) if "notes" in a.changes)
    assert "observações" in change.summary and change.changes["notes"] == ["Juros de\n  R$ 5,00", "Sem juros"]
