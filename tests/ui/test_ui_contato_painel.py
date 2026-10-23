"""Cadastro de Contatos: o painel nunca corta o formulário e a largura arrastada fica guardada."""
from finora.core import settings


def test_painel_cabe_o_formulario_e_lembra_a_largura(window):
    window.resize(1600, 900)
    window.go_to("contacts")
    page = window.page("contacts")
    page.resize(1400, 800)
    form_min = page.form.minimumSizeHint().width()
    assert page.form_scroll.minimumWidth() >= form_min               # abas e botões sempre inteiros
    assert page.splitter.sizes()[1] >= form_min
    page.splitter.moveSplitter(1400 - 600, 1)                       # arrasta: painel com ~600 px
    page._panel_moved()
    saved = settings.get_panel_width("contacts")
    assert saved and saved > form_min
    page.resize(1300, 800)
    assert abs(page.splitter.sizes()[1] - saved) <= 2                # a largura escolhida volta


def test_tela_estreita_o_cadastro_ocupa_tudo(window):
    window.go_to("contacts")
    page = window.page("contacts")
    page.resize(700, 700)
    page._new()
    assert page.left.isHidden() and not page.form_scroll.isHidden()
