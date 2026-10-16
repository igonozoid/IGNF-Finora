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


def test_arredondamento_registrado(session, plus, tmp_path):
    """Fase 2.4: valor com mais de 2 casas é arredondado e anotado; resíduo de REAL (0,1 + 0,2) não conta."""
    import sqlite3
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    con = sqlite3.connect(p)
    con.execute("UPDATE lancamentos SET valor=10.555 WHERE id=1")
    con.execute("UPDATE lancamentos SET valor=0.1 + 0.2 WHERE id=3")          # 0.30000000000000004
    con.execute("UPDATE contas SET saldo_inicial=2500.505 WHERE id=3")
    con.execute("UPDATE centros SET orcamento=3000.004 WHERE id=1")
    con.commit()
    con.close()
    with reader.open_copy(p) as c:
        r = mapper.import_companies(session, c)
    notes = {(x.table, x.mcc_id, x.column): x for x in r.rounding}
    assert set(notes) == {("lancamentos", 1, "valor"), ("contas", 3, "saldo_inicial"), ("centros", 1, "orcamento")}
    v = notes[("lancamentos", 1, "valor")]
    assert (v.original, v.imported, v.difference) == ("10.555", D("10.56"), D("0.005"))
    assert notes[("centros", 1, "orcamento")].imported == D("3000.00")
    assert session.get(Entry, r.entries[1]).amount == D("10.56")
    assert session.get(Entry, r.entries[3]).amount == D("0.30")                # ruído: só converte
    assert mapper.rounding_of(None) == (D("0.00"), None)


def test_exemplo_sem_arredondamento(imported):
    _s, r = imported
    assert r.rounding == []                                                     # 1333,33 + 1333,33 + 1333,34


def test_usuarios_entram_com_a_mesma_senha_do_mcc(imported):
    from finora.models import Permission, User, UserEntity
    from finora.services import permissions, users
    s, r = imported
    admin = s.get(User, r.users[1])
    oper = s.get(User, r.users[2])
    antigo = s.get(User, r.users[3])
    assert admin.is_admin and admin.email == "admin@exemplo.test" and not antigo.is_active
    assert users.authenticate(s, "operador@exemplo.test", GABARITO["senha_dos_usuarios"]).id == oper.id
    with pytest.raises(ValueError):
        users.authenticate(s, "operador@exemplo.test", "errada")
    ents = set(s.scalars(select(UserEntity.entity_id).where(UserEntity.user_id == oper.id)))
    assert ents == {r.entities[1]}                                          # só a empresa 1, como no MCC
    lv = lambda m: permissions.level(s, oper.id, r.entities[1], m)
    assert (lv("financial"), lv("contacts"), lv("reports"), lv("admin"), lv("stock")) == \
        ("full", "full", "read", "none", "none")                            # D1: o maior nível das áreas
    assert permissions.level(s, oper.id, r.entities[2], "financial") == "none"
    assert any("Operador Financeiro" in w and "acessos diferentes" in w for w in r.warnings)
    assert permissions.level(s, admin.id, r.entities[2], "admin") == "full"


def test_hash_do_mcc_e_usuario_que_ja_existe(session, plus, tmp_path):
    from finora.models import User
    from finora.services import users
    assert mapper.finora_hash("bcrypt$x$y") is None and mapper.finora_hash("lixo") is None
    users.create(session, name="Admin", email="admin@exemplo.test", password="outra-senha", is_admin=True)
    p = tmp_path / "mcc.db"
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    with reader.open_copy(p) as c:
        r = mapper.import_companies(session, c)
    assert session.scalar(select(func.count(User.id)).where(User.email == "admin@exemplo.test")) == 1
    assert users.authenticate(session, "admin@exemplo.test", "outra-senha")   # continua com a senha do Finora
    assert any("já existia" in w for w in r.warnings)


# ---------- reimportar sem duplicar (Fase 2.8) ----------
def _reimport(s, path):
    with reader.open_copy(path) as con:
        return mapper.import_companies(s, con)


def _counts(s):
    from finora.models import ImportMap, User
    return {m.__name__: s.scalar(select(func.count(m.id)))
            for m in (Entity, Account, Contact, CostCenter, Category, Entry, User, ImportMap)}


def test_importar_de_novo_nao_duplica(imported, tmp_path):
    s, r = imported
    before = _counts(s)
    r2 = _reimport(s, tmp_path / "mcc.db")
    assert _counts(s) == before
    assert r2.reimport and (r2.created, r2.updated, r2.trashed) == (0, 0, 0)
    assert (r2.entities, r2.accounts, r2.entries, r2.movements) == (r.entities, r.accounts, r.entries, r.movements)
    assert period_lock.locked_through(s, r.entities[1]) == date(2026, 3, 31)
    assert not r.reimport and r.created == len(r.entries) + len(r.movements)


def test_reimportar_aplica_o_que_mudou_no_mcc(imported, tmp_path):
    import sqlite3
    from datetime import date as d
    from finora.services.mcc_import import conference
    s, r = imported
    path = tmp_path / "mcc.db"
    con = sqlite3.connect(path)
    con.execute("UPDATE lancamentos SET valor=500 WHERE id=1")             # fevereiro: período fechado
    con.execute("UPDATE lancamentos SET situacao='V', data_pagamento='2026-10-14' WHERE id=20")
    con.execute("DELETE FROM lancamentos WHERE id=21")
    con.execute("CREATE TEMP TABLE novo AS SELECT * FROM lancamentos WHERE id=19")
    con.execute("UPDATE novo SET id=999, valor=77.70")
    con.execute("INSERT INTO lancamentos SELECT * FROM novo")
    con.execute("UPDATE contas SET saldo_inicial=11111.11 WHERE id=1")
    con.execute("UPDATE movbancarias SET valor=2500 WHERE id=4")
    con.execute("DELETE FROM movbancarias WHERE id=6")
    con.commit()
    con.close()
    accounts_before = s.scalar(select(func.count(Account.id)))
    with reader.open_copy(path) as c:
        r2 = mapper.import_companies(s, c)
        rep = conference.build(s, c, r2, [d.fromisoformat(x) for x in GABARITO["saldos"]])
    assert (r2.created, r2.updated, r2.trashed) == (1, 3, 2)
    assert s.get(Entry, r.entries[1]).amount == D("500.00")
    e20 = s.get(Entry, r.entries[20])
    assert (e20.status, e20.paid_date) == ("paid", date(2026, 10, 14))
    assert s.get(Entry, r.entries[21]) is None and trash.get(s, r.entries[21]).deleted_at is not None
    assert s.get(Entry, r.movements[6]) is None
    assert s.get(Entry, r2.entries[999]).amount == D("77.70")
    assert s.get(Account, r.accounts[1]).opening_balance == D("11111.11")
    assert s.get(Entry, r.movements[4]).amount == D("2500.00")
    assert s.scalar(select(func.count(Account.id))) == accounts_before
    assert period_lock.locked_through(s, r.entities[1]) == date(2026, 3, 31)  # reabriu só durante a atualização
    assert rep.ok, rep.problems


def test_reimportar_nao_mexe_no_que_e_do_finora(imported, tmp_path):
    s, r = imported
    mine = entity_admin.create(s, name="Minha casa", person_type="PF")
    mine_accounts = s.scalar(select(func.count(Account.id)).where(Account.entity_id == mine))
    cid = next(iter(r.contacts.values()))
    s.get(Contact, cid).name = "Nome que eu acertei"
    s.commit()
    _reimport(s, tmp_path / "mcc.db")
    assert s.get(Entity, mine).name == "Minha casa"
    assert s.scalar(select(func.count(Account.id)).where(Account.entity_id == mine)) == mine_accounts
    assert s.get(Contact, cid).name == "Nome que eu acertei"                # contato que já veio não é sobrescrito
