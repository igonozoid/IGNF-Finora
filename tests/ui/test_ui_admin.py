from PySide6.QtWidgets import QDialog

from finora.core import current, db
from finora.services import entity_admin, permissions, users
from finora.ui import session_dialogs, session_flow
from tests.ui.conftest import pump


def _make_users(window):
    """Ana (dona, administradora) com e-mail e senha + Carlos (usuário comum) só na entidade aberta."""
    with db.Session() as s:
        owner = users.owner(s)
        users.update(s, owner.id, name=owner.name, email="ana@x.com", is_admin=True)
        users.set_password(s, owner.id, "segredo1")
        carlos = users.create(s, name="Carlos", email="carlos@x.com", password="segredo1",
                              entity_ids=[window.profile.id])
    return owner.id, carlos


def test_administracao_usuarios_entidades_permissoes_e_auditoria(plus, window, dialogs, qtbot):
    window.go_to("admin")
    page = window.page("admin")
    ut = page.tabs["users"]
    assert ut.table.rowCount() == 1 and "abre direto" in ut.hint.text()
    # dar e-mail e senha ao dono
    ut._edit(ut.items[0])
    ut.email.setText("dona@x.com")
    ut.pw1.setText("segredo1")
    ut.pw2.setText("segredo1")
    ut.save_btn.click()
    assert ut.table.item(0, 4).text() == "Sim"
    # novo usuário
    ut._new()
    ut.name.setText("Carlos")
    ut.email.setText("carlos@x.com")
    ut.pw1.setText("outra123")
    ut.pw2.setText("outra12")
    ut.save_btn.click()
    assert "diferentes" in ut.error.text()
    ut.pw2.setText("outra123")
    ut.save_btn.click()
    assert ut.table.rowCount() == 2

    # nova entidade
    page.tab_buttons["entities"].click()
    et = page.tabs["entities"]
    et._new()
    et.name.setText("Padaria Sol")
    et.ptype.setCurrentIndex(et.ptype.findData("PJ"))
    et.doc.setText("11.222.333/0001-81")
    et.save_btn.click()
    assert et.table.rowCount() == 2 and "Trocar entidade" in window.statusBar().currentMessage()

    # permissões do Carlos: Relatórios = Nenhum
    page.tab_buttons["permissions"].click()
    pt = page.tabs["permissions"]
    pt.user.setCurrentIndex(next(i for i in range(pt.user.count()) if pt.user.itemText(i) == "Carlos"))
    pt.entity.setCurrentIndex(pt.entity.findData(window.profile.id))
    pt.groups["reports"].button(0).click()
    with db.Session() as s:
        carlos = next(u for u in users.list_users(s) if u.name == "Carlos")
        assert permissions.level(s, carlos.id, window.profile.id, "reports") == "none"

    # auditoria
    page.tab_buttons["audit"].click()
    at = page.tabs["audit"]
    texts = [at.table.item(r, 2).text() for r in range(at.table.rowCount())]
    assert any("Criou usuário \"Carlos\"" in x for x in texts)
    at.table.setCurrentCell(0, 0)
    assert at.details.toPlainText()


def test_permissao_de_leitura_esconde_e_trava(plus, window, dialogs, qtbot):
    _owner, carlos = _make_users(window)
    with db.Session() as s:
        permissions.set_level(s, carlos, window.profile.id, "financial", "read")
        user = users.get(s, carlos)
    current.set_user(user.id, user.name, user.is_admin)
    from finora.ui.main_window import MainWindow
    w = MainWindow(window.profile, user)
    qtbot.addWidget(w)
    assert "admin" not in w.visible_keys and "reports" in w.visible_keys
    assert not w.page("settings").admin_sections[0].isVisibleTo(w.page("settings"))
    w.go_to("entries")
    assert not w.header.new_btn.isVisible()
    page = w.page("entries")
    e = page.model.rows[0]
    page.open_by_id(e.id)
    page.form.desc.setText("Mudou")
    page.form._save()
    assert "só de leitura" in page.form.error.text()
    current.clear()


def test_login_e_escolha_de_entidade(plus, window, app_t, monkeypatch, qtbot):
    _make_users(window)
    with db.Session() as s:
        other = entity_admin.create(s, name="Padaria Sol")
    dlg = session_dialogs.LoginDialog(app_t, "ana@x.com")
    qtbot.addWidget(dlg)
    dlg.password.setText("errada")
    dlg.ok.click()
    assert "incorretos" in dlg.error.text()
    dlg.password.setText("segredo1")
    dlg.ok.click()
    assert dlg.result() == QDialog.Accepted and dlg.user.email == "ana@x.com"

    # fluxo: login pedido (há senha) e, sendo admin com 2 entidades, a lista aparece
    monkeypatch.setattr(session_dialogs.LoginDialog, "exec", lambda self: (
        setattr(self, "user", users.get(db.Session(), dlg.user.id)), QDialog.Accepted)[1])
    user = session_flow.pick_user(app_t)
    assert user.name and current.current.user_id == user.id
    monkeypatch.setattr(session_dialogs.EntityChooser, "exec", lambda self: (
        setattr(self, "entity_id", other), QDialog.Accepted)[1])
    profile = session_flow.pick_entity(user, app_t, ask=True)
    assert profile.name == "Padaria Sol"
    current.clear()


def test_trocar_de_entidade_na_mesma_janela(plus, window, monkeypatch):
    with db.Session() as s:
        other = entity_admin.create(s, name="Padaria Sol")
    monkeypatch.setattr(session_dialogs.EntityChooser, "exec", lambda self: (
        setattr(self, "entity_id", other), QDialog.Accepted)[1])
    window._apply_access()                                    # agora há 2 entidades
    window._switch_entity()
    assert window.profile.name == "Padaria Sol" and window.page("entries").profile.id == other
    assert window.sidebar._name.text() == "Padaria Sol" and window.isVisible()   # mesma janela
    window.go_to("accounts")
    assert [a.name for a in window.page("accounts")._items] == ["Conta principal"]


def test_trocar_entidade_com_uma_so_explica(window, dialogs):
    window._switch_entity()
    assert window.next_action is None and any("uma entidade só" in m for m in dialogs.shown)
    window._new_entity()
    assert window.current_key() == "admin" and window.page("admin").tabs["entities"].title.text() == "Nova entidade"


def test_entidade_autopreenche_pelo_cnpj(plus, window, monkeypatch):
    from finora.services import doc_lookup
    window.go_to("admin")
    tab = window.page("admin").tabs["entities"]
    tab._new()
    monkeypatch.setattr(doc_lookup, "cnpj", lambda n: doc_lookup.CompanyData(
        "IGNF PROJETOS LTDA", "IGNF", "ATIVA", {"city": "Teutônia", "state": "RS", "phone": "(51) 98101-6345"}))
    tab.doc.setText("46896045000197")
    tab.lookup.click()
    assert tab.ptype.currentData() == "PJ" and tab.name.text() == "IGNF"
    assert tab.det["city"].text() == "Teutônia" and "Preenchi" in tab.lookup_note.text()
