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


def test_conta_compartilhada(plus, window):
    from finora.services import accounts, entity_admin
    with db.Session() as s:
        other = entity_admin.create(s, name="Padaria Sol")
    page = _accounts(window)
    assert not page.shared.isHidden() and not page.shared.isChecked()      # edição com várias entidades
    page.kind_box.setCurrentIndex(page.kind_box.findData("card"))
    assert page.shared.isHidden()                                           # cartão não pode
    page.name_edit.setText("Itaú da família")
    page.kind_box.setCurrentIndex(page.kind_box.findData("bank"))
    page.balance_edit.setText("500")
    page.shared.setChecked(True)
    page.save_btn.click()
    itau = next(a for a in page._items if a.name == "Itaú da família")
    assert itau.shared
    with db.Session() as s:
        assert itau.id in [a.id for a in accounts.list_accounts(s, other)]   # aparece na outra entidade
    page._edit(itau.id)
    assert page.shared.isChecked()


def test_cheque_especial_na_conta_do_banco(window):
    from datetime import date, timedelta
    from decimal import Decimal as D
    from finora.services import entries
    from finora.services.entries import EntryData
    page = _accounts(window)
    page.kind_box.setCurrentIndex(page.kind_box.findData("cash"))
    assert page.card_box.isHidden()                                       # carteira: sem limite
    page.kind_box.setCurrentIndex(page.kind_box.findData("bank"))
    assert not page.card_box.isHidden() and page.closing_spin.isHidden()  # banco: só o limite
    assert page.limit_lbl.label.text() == "Limite do cheque especial"
    page.name_edit.setText("Itaú PJ")
    page.balance_edit.setText("100,00")
    page.limit_edit.setText("500,00")
    page.save_btn.click()
    itau = next(a for a in page._items if a.name == "Itaú PJ")
    assert itau.credit_limit == D("500.00")
    with db.Session() as s:
        entries.create(s, window.profile.id, EntryData(kind="expense", description="Folha", amount=D("900"),
                                                       due_date=date.today() + timedelta(days=3), account_id=itau.id))
    page.refresh()
    text = " ".join(lbl.text() for card in page.findChildren(type(page.form), "card")
                    for lbl in card.findChildren(type(page.form_title)))
    assert "Cheque especial R$ 500,00 · disponível R$ 600,00" in text
    assert "passa do limite do cheque especial" in text
    window.go_to("dashboard")                                             # Dashboard: valor em vermelho com aviso
    dash = window.page("dashboard")
    dash.refresh()
    tips = [lbl.toolTip() for lbl in dash.findChildren(type(page.form_title))]
    assert any("passa do limite do cheque especial" in t for t in tips)


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


def test_contato_rg_ie_bairro_pessoa_de_contato_e_banco(plus, window, monkeypatch):
    from finora.services import doc_lookup
    window.go_to("contacts")
    page = window.page("contacts")
    page._new()
    f = page.form
    doc2_label = f.doc2_box.itemAt(0).widget().label
    assert doc2_label.text() == "RG"
    f.type_group.button(1).click()                                       # PJ
    assert doc2_label.text() == "Inscrição estadual"
    f.name.setText("Cooperativa Serra Verde")
    f.details["document2"].setText("987.654.321.000")
    f.details["contact_person"].setText("Ana, financeiro")
    monkeypatch.setattr(doc_lookup, "cep", lambda n: doc_lookup.AddressData(
        "37010-000", "Av. Brasil, Industrial", "Varginha", "MG", "Industrial"))
    f.details["zip_code"].setText("37010000")
    f._lookup_cep()
    assert f.details["address"].text() == "Av. Brasil" and f.details["district"].text() == "Industrial"
    for key, value in (("bank_name", "001 - Banco do Brasil"), ("bank_branch", "4321"),
                       ("bank_account", "11111-1"), ("bank_holder", "Cooperativa Serra Verde")):
        f.details[key].setText(value)
    f.save_btn.click()
    with db.Session() as s:
        c = next(x for x in contacts.list_contacts(s, window.profile.id) if x.name == "Cooperativa Serra Verde")
    assert (c.get("document2"), c.get("contact_person"), c.get("district")) == \
        ("987.654.321.000", "Ana, financeiro", "Industrial")
    assert (c.get("bank_name"), c.get("bank_branch"), c.get("bank_account")) == \
        ("001 - Banco do Brasil", "4321", "11111-1")


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


def test_marcar_contato_categoria_e_centro_como_compartilhados(plus, window):
    from finora.services import categories, contacts, cost_centers, entity_admin
    from finora.core import db
    with db.Session() as s:
        entity_admin.create(s, name="Padaria Sol")
    window.go_to("contacts")
    page = window.page("contacts")
    page._new()
    f = page.form
    assert not f.shared.isHidden()
    f.name.setText("Contador Silva")
    f.shared.setChecked(True)
    f._save()
    window.go_to("cost_centers")
    cc = window.page("cost_centers")
    cc.name_edit.setText("Obra")
    cc.shared.setChecked(True)
    cc.save_btn.click()
    window.go_to("categories")
    cat = window.page("categories")
    cat._new_group()
    cat.name_edit.setText("Família")
    cat.shared.setChecked(True)
    cat._save()
    with db.Session() as s:
        other = max(e.id for e in entity_admin.list_entities(s))
        assert "Contador Silva" in [c.name for c in contacts.list_contacts(s, other)]
        assert "Obra" in [c.name for c in cost_centers.list_centers(s, other, 2026, 10)]
        assert "Família" in [g.name for g in categories.groups(s, other)]


def test_free_nao_mostra_compartilhar(window):
    window.go_to("contacts")
    assert window.page("contacts").form.shared.isHidden()


def test_regras_automaticas_preenchem_o_lancamento_novo(window, monkeypatch):
    from finora.ui.rules_dialog import RulesDialog
    window.go_to("categories")
    page = window.page("categories")

    def fake_exec(dlg):
        assert dlg.empty.isVisible() or not dlg.items
        dlg.text.setText("enel")
        dlg.category.setCurrentIndex(next(i for i in range(dlg.category.count())
                                          if dlg.category.itemText(i).endswith("Luz")))
        dlg.save()
        assert [r.text for r in dlg.items] == ["enel"] and dlg.error.isHidden()
        dlg.new_rule()
        dlg.text.setText("x")
        dlg.save()
        assert not dlg.error.isHidden()                      # texto curto demais / sem categoria
        return 0

    monkeypatch.setattr(RulesDialog, "exec", fake_exec)
    page.rules_btn.click()
    window.new_entry()
    form = window.page("entries").form
    form.desc.setText("Boleto ENEL outubro")
    form.desc.editingFinished.emit()
    assert form.category.currentText().endswith("Luz") and not form.rule_note.isHidden()


def test_filtro_a_revisar_so_aparece_quando_ha(window):
    from sqlalchemy import update
    from finora.models import Contact
    window.go_to("contacts")
    page = window.page("contacts")
    review = next(b for b in page.filter_group.buttons() if b.property("role_key") == "review")
    assert not review.isHidden()                       # os contatos digitados nos lançamentos do exemplo (4.6)
    with db.Session() as s:
        s.execute(update(Contact).values(needs_review=False))
        s.commit()
    page.refresh()
    assert review.isHidden()
    with db.Session() as s:
        cid = contacts.create(s, window.profile.id, name="Posto Beira Rio")
        s.get(Contact, cid).needs_review = True
        s.commit()
    page.refresh()
    assert not review.isHidden() and review.text() == "A revisar (1)"
    review.click()
    assert [c.name for c in page._items] == ["Posto Beira Rio"]
    page.form.open_contact(page._items[0])
    page.form.save_btn.click()                                     # salvar tira a marca
    assert review.text() == "A revisar (0)"
