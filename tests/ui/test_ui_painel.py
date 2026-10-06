from datetime import date

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from finora.core import license_key, licensing
from finora.services import backup
from finora.ui.dashboard_page import ClickRow


# ---------- Dashboard ----------
def test_dashboard_numeros_e_vencimentos(window):
    window.go_to("dashboard")
    page = window.page("dashboard")
    assert page.k_balance.value.text() == "R$ 6.000,00"        # 1.000 + salário pago de 5.000
    assert page.k_result.value.text().startswith("R$ 2.")      # 5.000 - aluguel - luz - mercado
    rows = page.findChildren(ClickRow)
    assert rows                                                 # há vencimentos nos próximos 7 dias
    rows[0].clicked.emit()                                      # clique abre o lançamento
    assert window.current_key() == "entries" and window.page("entries").form.editing is not None


# ---------- Relatórios ----------
def test_dre_regimes_e_subcategorias(window):
    window.go_to("reports")
    dre = window.page("reports").views["dre"]
    rep = dre.model.rep
    assert rep.row("receitas").total == 5000
    assert rep.row("livre").total == rep.row("sobra").total    # sem investimentos no exemplo
    dre.regime.setCurrentIndex(dre.regime.findData("cash"))
    assert dre.model.rep.row("moradia").total == 0             # nada de moradia pago ainda
    dre.details.setChecked(True)
    assert any(r.style == "detail" for r in dre.model.rep.rows)


def test_fluxo_de_caixa_e_cadeados(window, dialogs):
    window.go_to("reports")
    page = window.page("reports")
    page.group.button(1).click()
    flow = page.views["flow"]
    assert flow.k_start.value.text() == "R$ 6.000,00"
    assert flow.model.rowCount() >= 2
    next(b for b, _l, key in page.buttons if key == "budget").click()   # Orçado x realizado: edição paga
    assert any("Orçado x realizado" in t for t in dialogs.shown)


# ---------- Configurações ----------
def test_backup_manual_e_restaurar(window, dialogs, data_dir):
    window.go_to("settings")
    page = window.page("settings")
    dest = data_dir / "pendrive" / "copia.db"
    dialogs.save_path = str(dest)
    page.backup_btn.click()
    assert dest.exists() and "Último backup manual" in page.last_lbl.text()
    dialogs.open_path = str(dest)
    dialogs.choice = "Restaurar"
    page.restore_btn.click()
    assert "REINICIAR" in dialogs.shown                         # restaurou e pediu para reabrir
    assert any(p.name.startswith(backup.SAFETY_PREFIX) for p in (data_dir / "backups").glob("*.db"))


def test_restaurar_arquivo_que_nao_e_backup(window, dialogs, data_dir):
    window.go_to("settings")
    junk = data_dir / "lixo.db"
    junk.write_text("não sou um banco")
    window.page("settings")._restore(junk)
    assert any("não é um backup" in t for t in dialogs.shown) and "REINICIAR" not in dialogs.shown


def test_ativar_licenca(window, dialogs, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", pub)
    window.go_to("settings")
    page = window.page("settings")
    page.key_edit.setPlainText("FNR1-ERRADA")
    page._activate()
    assert page.key_error.isVisible() and "REINICIAR" not in dialogs.shown
    key = license_key.encode(license_key.License("plus", "Rodrigo", date.today(), None, 1), priv)
    page.key_edit.setPlainText(key)
    page._activate()
    assert "REINICIAR" in dialogs.shown and licensing.current_edition().value == "plus"


# ---------- Perfil ----------
def test_editar_perfil_atualiza_o_app_todo(window):
    from finora.core import db
    from finora.services import accounts
    window.go_to("settings")
    page = window.page("settings")
    assert page.name_edit.text() == "Rodrigo" and not page.profile_save.isEnabled()
    page.name_edit.setText("Rodrigo Silva")
    assert page.profile_save.isEnabled()
    page.currency_box.setCurrentIndex(page.currency_box.findData("USD"))
    assert page.currency_note.isVisible() and "não são convertidos" in page.currency_note.text()
    assert not page.accounts_too.isVisible()                 # Free: as contas mudam junto, sem escolha
    page.profile_save.click()
    assert window.profile.name == "Rodrigo Silva" and window.profile.currency == "USD"
    assert window.sidebar._name.text() == "Rodrigo Silva" and "USD" in window.sidebar._sub.text()
    assert window.tabs._name.text() == "Rodrigo Silva"
    with db.Session() as s:
        assert {a.currency for a in accounts.list_accounts(s, window.profile.id)} == {"USD"}
    window.go_to("entries")
    assert window.page("entries").tot_pay.text().startswith("US$")   # valores já com o símbolo novo
    window.go_to("dashboard")
    assert window.page("dashboard").k_balance.value.text() == "US$ 6.000,00"
    window.go_to("accounts")
    assert window.page("accounts").currency_box.currentData() == "USD"


def test_perfil_nome_vazio_nao_salva(window):
    window.go_to("settings")
    page = window.page("settings")
    page.name_edit.setText("  ")
    page.profile_save.click()
    assert page.profile_error.isVisible() and window.profile.name == "Rodrigo"


# ---------- relatórios em lista ----------
def _report(window, key):
    from finora.ui.reports_page import REPORTS
    window.go_to("reports")
    page = window.page("reports")
    page.group.button(next(i for i, r in enumerate(REPORTS) if r[0] == key)).click()
    return page.views[key]


def test_extrato_por_conta(window):
    view = _report(window, "statement")
    assert view.account.currentText() == "Nubank"
    texts = [view.table.item(r, 1).text() for r in range(view.table.rowCount())]
    assert texts[0] == "Saldo anterior" and "Salário" in texts
    assert "Saldo final" in view.footer.text()


def test_por_categoria_e_por_contato(window):
    view = _report(window, "category")
    cats = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert "Receitas › Salário" in cats and "Moradia › Aluguel ou financiamento" in cats
    view = _report(window, "contact")
    names = [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert {"Empresa X", "Imobiliária", "Enel"} <= set(names)


def test_inadimplencia_e_duplo_clique_abre_lancamento(window):
    from datetime import date
    view = _report(window, "overdue")
    if date.today().day == 1:                                      # no dia 1 a luz do exemplo não está atrasada
        assert view.empty.isVisible()
        return
    texts = [view.table.item(r, 1).text() for r in range(view.table.rowCount())]
    assert texts[0].startswith("Você deve") and "Conta de luz" in texts
    view._double(texts.index("Conta de luz"), 1)
    assert window.current_key() == "entries" and window.page("entries").form.editing.description == "Conta de luz"


def test_backup_na_nuvem_escolher_pasta_e_ao_fechar(plus, window, dialogs, tmp_path, monkeypatch):
    from finora import __main__ as app_main
    from finora.core import settings
    from finora.services import backup
    cloud = tmp_path / "Dropbox"
    cloud.mkdir()
    monkeypatch.setattr(backup, "cloud_candidates", lambda home=None: [("Dropbox", cloud)])
    page = window.page("settings")
    page._fill_cloud_box()
    page.cloud_box.setCurrentIndex(page.cloud_box.findData(str(cloud)))
    page._cloud_chosen()
    assert settings.get_cloud_folder() == str(cloud)
    assert len(list((cloud / "IGNF-Finora").glob("finora-*.db"))) == 1          # já envia na hora
    assert page.cloud_rows.count() == 1 and "Nuvem" in page.cloud_rows.itemAt(0).widget().findChildren(
        type(page.cloud_status))[1].text()
    # ao fechar o app
    (cloud / "IGNF-Finora" / next(iter((cloud / "IGNF-Finora").glob("*.db"))).name).unlink()
    app_main.cloud_backup_on_close()
    assert len(list((cloud / "IGNF-Finora").glob("finora-*.db"))) == 1
    # desligar
    page.cloud_box.setCurrentIndex(0)
    page._cloud_chosen()
    assert settings.get_cloud_folder() == "" and not page.cloud_now.isEnabled()


def test_backup_na_nuvem_bloqueado_na_free(window):
    assert window.page("settings").cloud_box is None


def test_relatorio_analitico_e_menor_saldo_no_fluxo(window, qtbot):
    window.go_to("reports")
    rp = window.page("reports")
    rp._select(next(i for i, (_b, _l, key) in enumerate(rp.buttons) if key == "analytical"))
    view = rp.views["analytical"]
    view.period.setCurrentIndex(view.period.findData("1m"))
    descr = [view.table.item(r, 1).text() for r in range(view.table.rowCount())]
    assert "Salário" in descr and "Mercado" in descr and "lançamentos" in view.footer.text()
    view.kind.setCurrentIndex(view.kind.findData("income"))
    assert all(view.table.item(r, 1).text() != "Mercado" for r in range(view.table.rowCount()))
    flow = rp.views["flow"]
    flow.refresh()
    assert flow.alert.text()                         # sempre mostra o ponto mais apertado do caixa
