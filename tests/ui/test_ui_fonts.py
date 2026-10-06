from PySide6.QtGui import QFontDatabase, QFontInfo

from finora.ui import fonts, theme


def test_fontes_ibm_plex_embutidas(qapp):
    families = fonts.load()
    assert {"IBM Plex Sans", "IBM Plex Mono"} <= families
    assert (fonts.FONTS_DIR / "LICENSE-IBM-Plex.txt").exists()          # licença OFL vai junto
    styles = QFontDatabase.styles("IBM Plex Sans")
    assert {"Regular", "Bold"} <= set(styles)
    assert QFontInfo(theme.mono_font()).family() == "IBM Plex Mono"     # colunas de valor usam a Plex Mono
