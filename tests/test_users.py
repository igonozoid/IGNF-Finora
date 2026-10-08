from datetime import date
from decimal import Decimal as D

import pytest

from finora.core import current
from finora.core.licensing import LimitError
from finora.models import User
from finora.services import accounts, audit, entity_admin, entries, permissions, users
from finora.services.entries import EntryData


def test_primeiro_uso_cria_o_administrador_sem_senha(session, profile):
    (u,) = users.list_users(session)
    assert (u.name, u.is_admin, u.has_password, u.entities) == ("Ana", True, False, (profile.id,))
    assert not users.needs_login(session) and users.owner(session).id == u.id


def test_senha_e_login(session, profile):
    s = session
    u = users.owner(s)
    with pytest.raises(ValueError, match="e-mail"):
        users.set_password(s, u.id, "segredo1")
    users.update(s, u.id, name="Ana", email="Ana@Exemplo.com", is_admin=True)
    with pytest.raises(ValueError, match="6 caracteres"):
        users.set_password(s, u.id, "123")
    users.set_password(s, u.id, "segredo1")
    stored = s.get(User, u.id).password_hash
    assert stored.startswith("scrypt$") and "segredo1" not in stored
    assert users.needs_login(s)
    assert users.authenticate(s, "ana@exemplo.com", "segredo1").id == u.id
    with pytest.raises(ValueError, match="incorretos"):
        users.authenticate(s, "ana@exemplo.com", "errada")
    users.set_password(s, u.id, None)                      # um usuário só: pode tirar a senha
    assert not users.needs_login(s)


def test_limite_de_usuarios_e_admin(session, profile, plus):
    s = session
    owner = users.owner(s)
    with pytest.raises(ValueError, match="e-mail"):
        users.create(s, name="Carlos")                     # com mais de um, todos precisam de e-mail
    users.update(s, owner.id, name="Ana", email="ana@x.com", is_admin=True)
    c = users.create(s, name="Carlos", email="carlos@x.com", password="segredo1")
    users.create(s, name="Contador", email="cont@x.com", password="segredo1")
    with pytest.raises(LimitError, match="até 3"):         # Plus: 3 usuários
        users.create(s, name="Quarto", email="q@x.com", password="segredo1")
    with pytest.raises(ValueError, match="administrador"):
        users.update(s, owner.id, name="Ana", email="ana@x.com", is_admin=False)
    with pytest.raises(ValueError, match="todos precisam de senha"):
        users.set_password(s, c, None)
    assert users.needs_login(s)


def test_free_tem_um_usuario_so(session, profile):
    with pytest.raises(LimitError, match="1 usuário"):
        users.create(session, name="Outro", email="o@x.com")


def test_permissoes_por_modulo(session, profile, plus):
    s = session
    owner = users.owner(s)
    users.update(s, owner.id, name="Ana", email="ana@x.com", is_admin=True)
    c = users.create(s, name="Carlos", email="carlos@x.com", password="segredo1", entity_ids=[profile.id])
    assert permissions.level(s, owner.id, profile.id, "admin") == "full"
    assert permissions.levels(s, c, profile.id) == permissions.DEFAULTS
    permissions.set_level(s, c, profile.id, "reports", "none")
    assert permissions.level(s, c, profile.id, "reports") == "none"
    with pytest.raises(ValueError, match="Administrador"):
        permissions.set_level(s, owner.id, profile.id, "reports", "read")
    other = entity_admin.create(s, name="Padaria Sol", person_type="PJ", document="11.222.333/0001-81")
    assert permissions.level(s, c, other, "financial") == "none"       # sem acesso à outra entidade
    assert permissions.entities_for(s, owner.id) == [profile.id, other]  # admin ganha acesso à nova
    assert permissions.at_least("full", "read") and not permissions.at_least("read", "full")


def test_entidades_limite_e_validacoes(session, profile, plus):
    s = session
    e = entity_admin.create(s, name="Padaria Sol", person_type="PJ", document="11222333000181")
    v = next(x for x in entity_admin.list_entities(s) if x.id == e)
    assert (v.document_fmt, v.accounts, v.users) == ("11.222.333/0001-81", 1, 1)
    with pytest.raises(ValueError, match="CNPJ inválido"):
        entity_admin.create(s, name="X", person_type="PJ", document="11222333000180")
    with pytest.raises(ValueError, match="Já existe"):
        entity_admin.create(s, name="padaria sol")
    for i in range(8):
        entity_admin.create(s, name=f"E{i}")
    with pytest.raises(LimitError, match="até 10"):
        entity_admin.create(s, name="Décima primeira")


def test_auditoria_registra_quem_e_o_que(session, profile):
    s = session
    current.set_user(None, "Ana", True)
    bank = accounts.list_accounts(s, profile.id)[0].id
    (eid,) = entries.create(s, profile.id, EntryData(kind="expense", description="Luz", amount=D("100"),
                                                     due_date=date(2026, 10, 5), account_id=bank))
    entries.set_paid(s, eid, True, date(2026, 10, 6))
    bank_acc = entries.get(s, eid)
    entries.update(s, eid, EntryData(kind="expense", description="Luz de outubro", amount=D("120"),
                                     due_date=date(2026, 10, 5), account_id=bank, paid=True,
                                     paid_date=bank_acc.paid_date))
    entries.delete(s, eid)
    audit.note(s, profile.id, "Importou extrato OFX (4 linhas)")
    log = audit.list_log(s, profile.id)
    texts = [a.summary for a in log]
    assert texts[0] == "Importou extrato OFX (4 linhas)"
    assert texts[1].startswith("Mandou para a lixeira lançamento \"Luz de outubro\"")
    assert any(t.startswith("Alterou lançamento") and "descrição" in t and "valor" in t for t in texts)
    assert any(t.startswith("Baixou pagamento \"Luz\"") for t in texts)
    assert any(t.startswith("Criou lançamento \"Luz\" — R$ 100,00") for t in texts)
    assert all(a.user == "Ana" for a in log[:5])            # as linhas mais antigas são do cadastro inicial
    changed = next(a for a in log if a.summary.startswith("Alterou lançamento"))
    assert changed.changes["amount"][1] in ("120", "120.00")
    assert audit.list_log(s, profile.id, search="baixou")[0].summary.startswith("Baixou")
    current.clear()


def test_pin_para_abrir_com_um_usuario(session, profile):
    s = session
    u = users.owner(s)
    with pytest.raises(ValueError, match="4 a 8 números"):
        users.set_pin(s, u.id, "12a4")
    users.set_pin(s, u.id, "2468")
    assert users.needs_login(s) and users.pin_mode(s).id == u.id
    assert users.authenticate_pin(s, "2468").id == u.id
    with pytest.raises(ValueError, match="PIN incorreto"):
        users.authenticate_pin(s, "1111")
    users.set_pin(s, u.id, None)
    assert not users.needs_login(s) and users.pin_mode(s) is None
