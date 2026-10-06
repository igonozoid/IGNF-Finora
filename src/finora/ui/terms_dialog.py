"""Termos de uso e aviso de privacidade (assets/termos.md)."""
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QTextBrowser, QVBoxLayout

from finora.ui.widgets import button

TERMS_FILE = Path(__file__).resolve().parents[1] / "assets" / "termos.md"
TERMS_VERSION = "1"


def terms_text() -> str:
    return TERMS_FILE.read_text(encoding="utf-8")


class TermsDialog(QDialog):
    """Mostra os termos. Com `ask=True`, só libera "Continuar" depois de marcar que leu e aceita."""

    def __init__(self, parent=None, ask: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Termos de uso e privacidade")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        view = QTextBrowser(openExternalLinks=True)
        view.setMarkdown(terms_text())
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        self.accept_chk = QCheckBox("Li e aceito os termos de uso e o aviso de privacidade")
        row.addWidget(self.accept_chk)
        row.addStretch(1)
        ok = button("Continuar" if ask else "Fechar", "primary")
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)
        self.accept_chk.setVisible(ask)
        if ask:
            ok.setEnabled(False)
            self.accept_chk.toggled.connect(ok.setEnabled)
        ok.clicked.connect(self.accept)
