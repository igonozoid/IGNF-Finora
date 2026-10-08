from finora.core import db
from finora.services import entity_admin
from finora.ui.receipt_dialog import ReceiptDialog


def _entry(window, desc):
    window.go_to("entries")
    return next(e for e in window.page("entries").model.rows if e.description == desc)


def test_recibo_de_despesa_no_formato_ignccontrol_e_pdf(window, qtbot, tmp_path):
    with db.Session() as s:
        entity_admin.update_details(s, window.profile.id, city="Teutônia", state="RS", phone="(51) 98101-6345")
    aluguel = _entry(window, "Aluguel")
    dlg = ReceiptDialog(window, aluguel.id, window.page("entries").t)
    qtbot.addWidget(dlg)
    assert dlg.other_name.text() == "Imobiliária" and dlg.two.isChecked()       # 2 vias por padrão
    assert (dlg.receipt.party, dlg.receipt.entity, dlg.receipt.signer) == ("Imobiliária", "Rodrigo", "Imobiliária")
    dlg.notes.setText("Pago via Pix")
    html = dlg.preview.toHtml()
    for text in ("RECIBO", "Pagamento para", "Emitido por", "mil e quinhentos reais", "Teutônia/RS", "2ª via",
                 "IMOBILIÁRIA", "Pago via Pix"):
        assert text in html, text
    pdf = tmp_path / "recibo.pdf"
    dlg.save_pdf(str(pdf))
    assert pdf.read_bytes()[:5] == b"%PDF-" and pdf.stat().st_size > 1000


def test_recibo_sem_contato_pede_o_nome(window, qtbot):
    mercado = _entry(window, "Mercado")
    dlg = ReceiptDialog(window, mercado.id, window.page("entries").t)
    qtbot.addWidget(dlg)
    assert not dlg.error.isHidden() and not dlg.print_btn.isEnabled()
    dlg.other_name.setText("Supermercado Bom Preço")
    assert dlg.error.isHidden() and dlg.print_btn.isEnabled()


def test_recibo_de_receita_quem_assina_e_a_entidade(window, qtbot):
    salario = _entry(window, "Salário")
    dlg = ReceiptDialog(window, salario.id, window.page("entries").t)
    qtbot.addWidget(dlg)
    assert dlg.receipt.party_label == "Recebido de" and dlg.receipt.signer == "Rodrigo"
    assert "Quem assina: Rodrigo" in dlg.signer.text() and not dlg.my_doc.isHidden()   # entidade sem CPF ainda


def test_botao_recibo_no_formulario(window, monkeypatch):
    opened = []
    monkeypatch.setattr(ReceiptDialog, "exec", lambda self: opened.append(self.receipt.reference) or 0)
    page = window.page("entries")
    aluguel = _entry(window, "Aluguel")
    page.open_by_id(aluguel.id)
    assert not page.form.receipt_btn.isHidden()
    page.form.receipt_btn.click()
    assert opened == ["Aluguel"]
    page.new_entry()
    assert page.form.receipt_btn.isHidden()                 # lançamento novo ainda não tem recibo
