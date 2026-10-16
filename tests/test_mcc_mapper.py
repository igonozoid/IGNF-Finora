"""Mapeamento MCC -> Finora (Fase 2.2), conferido com o gabarito do banco de exemplo (tools/gerar_mcc_exemplo.py)."""
import json
import shutil
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import func, select

from finora.core import settings
from finora.models import Account, Category, Contact, CostCenter, Entity, Entry
from finora.services import accounts, entity_admin, period_lock, trash
from finora.services.mcc_import import mapper, reader

DATA = Path(__file__).parent / "data"
GABARITO = json.loads((DATA / "mcc_exemplo_gabarito.json").read_text(encoding="utf-8"))


@pytest.fixture
def imported(session, plus, tmp_path):
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    with reader.open_copy(p) as con:
        r = mapper.import_companies(session, con)
    return session, r


def _live(s, eid, *kinds):
    q = select(Entry).where(Entry.entity_id == eid)
    if kinds:
        q = q.where(Entry.kind.in_(kinds))
    return list(s.scalars(q))


def test_empresas_viram_entidades(imported):
    s, r = imported
    agro, joao = (s.get(Entity, r.entities[i]) for i in (1, 2))
    assert (agro.name, agro.person_type, agro.document, agro.dre_model) == \
        ("Agro Exemplo Ltda", "PJ", "11222333000181", "business")
    assert (joao.name, joao.person_type, joao.dre_model) == ("João Exemplo", "PF", "personal")
    assert (agro.district, agro.city, agro.state, agro.zip_code) == ("Zona Rural", "Maria da Fé", "MG", "37517-000")
    assert agro.logo and entity_admin.uses_cost_centers(s, agro.id) and not entity_admin.uses_cost_centers(s, joao.id)
    assert period_lock.locked_through(s, agro.id) == date(2026, 3, 31)                 # aplicado no fim
    prefs = settings.get_entry_prefs(agro.id)
    assert (prefs.default_account, prefs.first_field) == (r.accounts[1], "document")


def test_totais_por_empresa_batem_com_o_mcc(imported):
    s, r = imported
    for mcc_id, g in GABARITO["por_empresa"].items():
        eid = r.entities[int(mcc_id)]
        rows = _live(s, eid, "income", "expense")
        total = lambda kind, status: sum((e.amount for e in rows if e.kind == kind and e.status == status), D(0))
        assert len(rows) == g["lancamentos_ativos"]
        assert (total("expense", "pending"), total("income", "pending")) == (D(str(g["a_pagar"])), D(str(g["a_receber"])))
        assert (total("expense", "paid"), total("income", "paid")) == (D(str(g["pago"])), D(str(g["recebido"])))
    deleted = s.scalar(select(func.count(Entry.id)).where(Entry.deleted_at.is_not(None))
                       .execution_options(**trash.WITH_DELETED))
    assert deleted == 2 + 1                                                             # 2 lançamentos + 1 movimentação


def test_saldos_batem_com_o_mcc_menos_o_pago_sem_data(imported):
    """D6: o lançamento 7 (pago sem data, conta 2, R$ 120) entra pago com o vencimento; no MCC ele não contava."""
    s, r = imported
    assert r.paid_without_date == [7]
    e7 = s.get(Entry, r.entries[7])
    assert e7.status == "paid" and e7.paid_date == date(2026, 4, 2)
    expected = GABARITO["saldos"]["2026-12-31"]
    bal = {}
    for mcc_id, eid in r.entities.items():
        bal.update({a.id: a.balance for a in accounts.list_accounts(s, eid, include_inactive=True)})
    for conta, g in expected.items():
        diff = D("-120.00") if conta == "2" else D("0")
        assert bal[r.accounts[int(conta)]] == D(str(g["realizado"])) + diff, g["descricao"]


def test_cadastros(imported):
    s, r = imported
    agro, joao = r.entities[1], r.entities[2]
    itau = s.get(Account, r.accounts[3])
    assert itau.shared and itau.entity_id == agro
    assert r.accounts[3] in [a.id for a in accounts.list_accounts(s, joao)]             # compartilhada aparece na PF
    bb = s.get(Account, r.accounts[1])
    assert (bb.kind, bb.credit_limit, bb.opening_balance) == ("bank", D("5000.00"), D("10000.00"))
    assert s.get(Account, r.accounts[2]).kind == "cash" and not s.get(Account, r.accounts[5]).is_active
    vendas = s.get(CostCenter, r.cost_centers[3])
    assert (vendas.applies_expense, vendas.applies_income, vendas.projection, vendas.budget) == \
        (False, True, D("20000.00"), None)
    coop = s.get(Contact, r.contacts[2])
    assert coop.is_customer and coop.contact_person == "Ana" and coop.district == "Industrial"
    insumos = s.get(Contact, r.contacts[1])
    assert (insumos.bank_name, insumos.bank_branch, insumos.bank_account) == ("341 - Itaú", "0123", "45678-9")
    assert s.get(Contact, r.contacts[4]).shared                                         # pessoa sem empresa
    groups = lambda eid: {c.name: c.dre_group for c in s.scalars(select(Category).where(
        Category.entity_id == eid, Category.parent_id.is_(None)))}
    assert groups(agro) == {"Despesas do MCC": "administrativas", "Receitas do MCC": "receita_bruta"}   # empresa
    assert groups(joao) == {"Despesas do MCC": "outras", "Receitas do MCC": "receitas"}                # pessoal
    items = {c.name for c in s.scalars(select(Category).where(Category.entity_id == agro,
                                                              Category.parent_id.is_not(None)))}
    assert {"Adubos e fertilizantes", "Venda de azeite", "Prestação de serviços"} <= items


def test_lancamentos_series_contatos_e_movimentacoes(imported):
    s, r = imported
    agro = r.entities[1]
    e6 = s.get(Entry, r.entries[6])
    assert (e6.amount, e6.notes, e6.document_no) == (D("1050.00"), "Pago com 5 dias de atraso: R$ 1.000,00 + R$ 50,00 "
                                                     "de juros", "OS-778")
    coop_e = s.get(Entry, r.entries[18])                                     # "COOPERATIVA AGRICOLA..." sem acento
    assert coop_e.contact_id == r.contacts[2]
    assert s.get(Entry, r.entries[2]).contact_id == r.contacts[4]           # maiúsculas, contato compartilhado
    assert r.contacts_created_from_text == ["Posto Beira Rio", "Folha de julho", "Imobiliária Central"]
    posto = s.scalars(select(Contact).where(Contact.name == "Posto Beira Rio")).one()
    assert posto.needs_review and not s.get(Contact, r.contacts[2]).needs_review   # do cadastro do MCC: não
    quinz = [s.get(Entry, r.entries[i]) for i in (14, 15, 16, 17)]
    assert len({e.series_id for e in quinz}) == 1 and [e.installment for e in quinz] == ["1/5", "2/5", "3/5", "4/5"]
    excl = trash.get(s, r.entries[23])
    assert excl.deleted_at is not None and excl.series_id == quinz[0].series_id
    sem_conta = s.get(Entry, r.entries[10])
    assert s.get(Account, sem_conta.account_id).name == "A definir (MCC)"
    kinds = sorted(s.get(Entry, i).kind if s.get(Entry, i) else "lixeira" for i in r.movements.values())
    assert kinds == ["deposit", "lixeira", "transfer", "transfer", "transfer", "withdrawal"]
    assert any("A definir (MCC)" in w for w in r.warnings) and any("OFX" in w for w in r.warnings)


def test_importa_so_a_empresa_escolhida_e_nome_repetido(session, plus, tmp_path):
    entity_admin.create(session, name="João Exemplo")
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    with reader.open_copy(p) as con:
        r = mapper.import_companies(session, con, companies=[2])
    assert list(r.entities) == [2] and session.get(Entity, r.entities[2]).name == "João Exemplo (MCC)"
    assert 3 not in r.accounts or session.get(Account, r.accounts[3]).entity_id == r.entities[2]
    with pytest.raises(ValueError, match="Nenhuma empresa"):
        with reader.open_copy(p) as con:
            mapper.import_companies(session, con, companies=[99])


def test_dados_ruins_viram_aviso_sem_parar(session, plus, tmp_path):
    import sqlite3
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    con = sqlite3.connect(p)
    con.execute("UPDATE empresas SET documento='11.111.111/1111-11', uf='XX' WHERE id=1")
    con.execute("UPDATE pessoas SET documento='123', email='sem-arroba' WHERE id=1")
    con.commit()
    con.close()
    with reader.open_copy(p) as c:
        r = mapper.import_companies(session, c)
    agro = session.get(Entity, r.entities[1])
    assert agro.document is None and agro.state is None
    insumos = session.get(Contact, r.contacts[1])
    assert insumos.document is None and insumos.email is None and "Documento no MCC: 123" in insumos.notes
    text = " ".join(r.warnings)
    assert "CNPJ inválido" in text and "state \"XX\"" in text and "email \"sem-arroba\"" in text
    assert len(r.entries) == 28                                                 # importou tudo mesmo assim
