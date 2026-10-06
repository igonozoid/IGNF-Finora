from finora.core import settings
from finora.ui.receipt_dialog import ReceiptDialog


def _entry(window, desc):
    window.go_to(1)
    return next(e for e in window.pages[1].model.rows if e.description == desc)


def test_recibo_de_despesa_e_pdf(window, qtbot, tmp_path):
    aluguel = _entry(window, "Aluguel")
    dlg = ReceiptDialog(window, aluguel.id, window.pages[1].t)
    qtbot.addWidget(dlg)
    assert dlg.other_name.text() == "Imobiliária"                     # contato do lançamento
    assert dlg.receipt.payee == "Imobiliária" and dlg.receipt.payer == "Rodrigo"
    dlg.city.setText("Campinas")
    dlg.my_doc.setText("52998224725")
    html = dlg.preview.toHtml()
    assert "mil e quinhentos reais" in html and "Campinas" in html and "529.982.247-25" in html
    pdf = tmp_path / "recibo.pdf"
    dlg.save_pdf(str(pdf))
    assert pdf.read_bytes()[:5] == b"%PDF-" and pdf.stat().st_size > 1000
    assert settings.get_receipt_defaults() == ("Campinas", "52998224725")     # lembra para o próximo


def test_recibo_sem_contato_pede_o_nome(window, qtbot):
    mercado = _entry(window, "Mercado")
    dlg = ReceiptDialog(window, mercado.id, window.pages[1].t)
    qtbot.addWidget(dlg)
    assert not dlg.error.isHidden() and not dlg.print_btn.isEnabled()
    dlg.other_name.setText("Supermercado Bom Preço")
    assert dlg.error.isHidden() and dlg.print_btn.isEnabled()
    dlg.two.setChecked(True)
    assert "2ª via" in dlg.preview.toHtml()


def test_recibo_de_receita_quem_assina_e_voce(window, qtbot):
    salario = _entry(window, "Salário")
    dlg = ReceiptDialog(window, salario.id, window.pages[1].t)
    qtbot.addWidget(dlg)
    assert dlg.receipt.payer == "Empresa X" and dlg.receipt.payee == "Rodrigo"
    assert "Quem assina: Rodrigo" in dlg.signer.text()
