from finora.core import db
from finora.services import contacts


# ---------- Contas ----------
def _accounts(window):
    window.go_to("accounts")
    return window.page("accounts")


def _new_account(page, name, kind, balance):
    page.name_edit.setText(name)
    page.kind_box.setCurrentIndex(page.kind_box.findData(kind))
    page.balance_edit.setText(balance)
    page.save_btn.click()


def test_contas_criar_ate_o_limite_da_free(window, dialogs):
    page = _accounts(window)
    assert page.form_title.text() == "Nova conta" and page.panel_scroll.isVisible()
    _new_account(page, "nubank", "cash", "0")
    assert "Já existe" in page.form_error.text()
    _new_account(page, "Carteira", "cash", "abc")
    assert "inválido" in page.form_error.text()
    _new_account(page, "Carteira", "cash", "85,50")
    _new_account(page, "Cartão", "card", "300")
    assert [a.name for a in page._items] == ["Carteira", "Cartão", "Nubank"]
    assert page.lock.isVisible() and not page.form.isVisible()          # 3 contas: cadeado da Free
    assert page.currency_box.isEnabled() is False                        # moeda: recurso pago


def test_contas_editar_e_inativar(window):
    page = _accounts(window)
    nubank = page._items[0]
    page._edit(nubank.id)
    assert page.form_title.text().startswith("Editar conta") and page.cancel_btn.isVisible()
    page.name_edit.setText("Nubank PF")
    page.save_btn.click()
    assert page._items[0].name == "Nubank PF" and page.form_title.text() == "Nova conta"
    page._toggle(page._items[0].id, False)
    assert page._items == []
    page.show_inactive.setChecked(True)
    assert len(page._items) == 1 and not page._items[0].is_active


def test_contas_em_janela_estreita(window, qtbot):
    page = _accounts(window)
    window.resize(800, 480)
    qtbot.wait(20)
    assert not page.panel_scroll.isVisible() and page.left.isVisible()
    page.new_btn.click()
    assert page.panel_scroll.isVisible() and not page.left.isVisible()
    page.cancel_btn.click()
    assert page.left.isVisible()


# ---------- Categorias ----------
def _find(tree, name):
    for i in range(tree.topLevelItemCount()):
        g = tree.topLevelItem(i)
        if g.text(0).startswith(name):
            return g
        for j in range(g.childCount()):
            if g.child(j).text(0).startswith(name):
                return g.child(j)


def test_categorias_criar_e_inativar(window):
    window.go_to("categories")
    page = window.page("categories")
    assert page.tree.topLevelItemCount() == 9
    page.tree.setCurrentItem(_find(page.tree, "Lazer"))
    page._new_child()
    page.name_edit.setText("Cinema")
    page.save_btn.click()
    assert page.current.name == "Cinema" and page.current.dre_group == "lazer"
    assert not page.dre_box.isEnabled()                                 # subcategoria herda a DRE
    page._new_group()
    page.name_edit.setText("Pets")
    page.dre_box.setCurrentIndex(page.dre_box.findData("outras"))
    page.save_btn.click()
    assert _find(page.tree, "Pets") is not None
    page.tree.setCurrentItem(_find(page.tree, "Saúde"))
    page.toggle_btn.click()
    assert _find(page.tree, "Saúde") is None
    page.show_inactive.setChecked(True)
    assert "(inativa)" in _find(page.tree, "Saúde").text(0)


# ---------- Contatos ----------
def test_contatos_lista_filtros_e_cadastro(window):
    window.go_to("contacts")
    page = window.page("contacts")
    assert {c.name for c in page._items} == {"Empresa X", "Imobiliária", "Enel"}   # vieram dos lançamentos
    page.filter_group.button(1).click()                                  # "Me paga"
    assert [c.name for c in page._items] == ["Empresa X"]
    page.filter_group.button(0).click()
    page._new()
    f = page.form
    f.type_group.button(1).click()                                       # PJ
    assert f.doc_lbl.label.text() == "CNPJ"
    f.doc.setText("11222333000180")
    f.name.setText("Condomínio Sol")
    f.save_btn.click()
    assert "inválido" in f.error.text()
    f.doc.setText("11.222.333/0001-81")
    f.role_btns["supplier"].click()
    f.save_btn.click()
    assert f.title.text() == "Condomínio Sol"
    with db.Session() as s:
        c = next(x for x in contacts.list_contacts(s, window.profile.id) if x.name == "Condomínio Sol")
    assert c.document == "11222333000181" and c.roles == {"supplier"}


def test_contato_com_lancamentos_nao_e_excluido(window):
    window.go_to("contacts")
    page = window.page("contacts")
    row = next(i for i, c in enumerate(page._items) if c.name == "Enel")
    page.list.setCurrentRow(row)
    page.form.delete_btn.click()
    assert "não pode ser excluído" in page.form.error.text()


def test_autopreencher_tem_cadeado_na_free(window, dialogs):
    window.go_to("contacts")
    window.page("contacts").form.lookup.click()
    assert any("edições Plus e Pro" in t for t in dialogs.shown)


def test_contato_ampliado_com_abas(window):
    window.go_to("contacts")
    page = window.page("contacts")
    page._new()
    f = page.form
    f.name.setText("Maria Diarista")
    f.details["phone"].setText("(19) 99999-1234")
    f.tab_group.button(1).click()                                       # Endereço
    assert f.pages.currentIndex() == 1
    f.details["zip_code"].setText("13010050")
    f.details["city"].setText("Campinas")
    f.details["state"].setText("sp")
    f.tab_group.button(2).click()                                       # Bancário
    f.details["pix_key"].setText("maria@exemplo.com")
    f.tab_group.button(3).click()
    f.notes.setPlainText("Vem às terças")
    f.save_btn.click()
    with db.Session() as s:
        c = next(x for x in contacts.list_contacts(s, window.profile.id) if x.name == "Maria Diarista")
    assert (c.get("zip_code"), c.get("state"), c.get("pix_key"), c.get("notes")) == (
        "13010-050", "SP", "maria@exemplo.com", "Vem às terças")
    assert f.pages.currentIndex() == 0 and f.details["phone"].text() == "(19) 99999-1234"   # reabre em Dados
    f.details["email"].setText("sem-arroba")
    f.save_btn.click()
    assert "E-mail" in f.error.text()


def test_autopreencher_cnpj_e_cep(plus, window, monkeypatch):
    from finora.services import doc_lookup
    monkeypatch.setattr(doc_lookup, "cnpj", lambda n: doc_lookup.CompanyData(
        "ENERGIA PAULISTA S.A.", "ENEL", "BAIXADA", {"phone": "(11) 3333-4444", "city": "Sao Paulo", "state": "SP"}))
    monkeypatch.setattr(doc_lookup, "cep", lambda n: doc_lookup.AddressData("13015-002", "Rua A, Centro",
                                                                            "Campinas", "SP"))
    window.go_to("contacts")
    page = window.page("contacts")
    page._new()
    f = page.form
    f.lookup.click()                                   # PF: CPF não tem consulta pública
    assert "CPF não tem consulta" in f.error.text()
    f.type_group.button(1).click()                     # PJ
    f.doc.setText("11222333000181")
    f.details["city"].setText("Jundiaí")               # o que já foi digitado não é apagado
    f.lookup.click()
    assert f.name.text() == "ENEL" and f.doc.text() == "11.222.333/0001-81"
    assert f.details["phone"].text() == "(11) 3333-4444" and f.details["city"].text() == "Jundiaí"
    assert "situação BAIXADA" in f.sub.text()
    f.details["zip_code"].setText("13015002")
    f.cep_btn.click()
    assert (f.details["address"].text(), f.details["city"].text()) == ("Rua A, Centro", "Campinas")
