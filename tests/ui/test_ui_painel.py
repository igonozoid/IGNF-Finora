from datetime import date

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from finora.core import license_key, licensing
from finora.services import backup
from finora.ui.dashboard_page import ClickRow


# ---------- Dashboard ----------
def test_dashboard_numeros_e_vencimentos(window):
    window.go_to(0)
    page = window.pages[0]
    assert page.k_balance.value.text() == "R$ 6.000,00"        # 1.000 + salário pago de 5.000
    assert page.k_result.value.text().startswith("R$ 2.")      # 5.000 - aluguel - luz - mercado
    rows = page.findChildren(ClickRow)
    assert rows                                                 # há vencimentos nos próximos 7 dias
    rows[0].clicked.emit()                                      # clique abre o lançamento
    assert window.stack.currentIndex() == 1 and window.pages[1].form.editing is not None


# ---------- Relatórios ----------
def test_dre_regimes_e_subcategorias(window):
    window.go_to(5)
    dre = window.pages[5].views["dre"]
    rep = dre.model.rep
    assert rep.row("receitas").total == 5000
    assert rep.row("livre").total == rep.row("sobra").total    # sem investimentos no exemplo
    dre.regime.setCurrentIndex(dre.regime.findData("cash"))
    assert dre.model.rep.row("moradia").total == 0             # nada de moradia pago ainda
    dre.details.setChecked(True)
    assert any(r.style == "detail" for r in dre.model.rep.rows)


def test_fluxo_de_caixa_e_cadeados(window, dialogs):
    window.go_to(5)
    page = window.pages[5]
    page.group.button(1).click()
    flow = page.views["flow"]
    assert flow.k_start.value.text() == "R$ 6.000,00"
    assert flow.model.rowCount() >= 2
    page.buttons[2][0].click()                                  # Orçado x realizado: edição paga
    assert any("Orçado x realizado" in t for t in dialogs.shown)


# ---------- Configurações ----------
def test_backup_manual_e_restaurar(window, dialogs, data_dir):
    window.go_to(6)
    page = window.pages[6]
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
    window.go_to(6)
    junk = data_dir / "lixo.db"
    junk.write_text("não sou um banco")
    window.pages[6]._restore(junk)
    assert any("não é um backup" in t for t in dialogs.shown) and "REINICIAR" not in dialogs.shown


def test_ativar_licenca(window, dialogs, monkeypatch):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", pub)
    window.go_to(6)
    page = window.pages[6]
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
    window.go_to(6)
    page = window.pages[6]
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
    window.go_to(1)
    assert window.pages[1].tot_pay.text().startswith("US$")   # valores já com o símbolo novo
    window.go_to(0)
    assert window.pages[0].k_balance.value.text() == "US$ 6.000,00"
    window.go_to(2)
    assert window.pages[2].currency_box.currentData() == "USD"


def test_perfil_nome_vazio_nao_salva(window):
    window.go_to(6)
    page = window.pages[6]
    page.name_edit.setText("  ")
    page.profile_save.click()
    assert page.profile_error.isVisible() and window.profile.name == "Rodrigo"
