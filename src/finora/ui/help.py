"""Ajuda (F1) a partir de assets/ajuda.md e "Enviar relatório de problema"."""
import re
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QTextBrowser,
    QVBoxLayout,
)

from finora.core import vendor
from finora.ui import theme
from finora.ui.widgets import button

HELP_FILE = Path(__file__).resolve().parents[1] / "assets" / "ajuda.md"
_HEAD = re.compile(r"^## (.+?)\s*\{#([\w-]+)\}\s*$", re.MULTILINE)


def sections(text: str | None = None) -> list[tuple[str, str, str]]:
    """[(chave, título, texto)] das seções '## Título {#chave}' do manual."""
    text = text if text is not None else HELP_FILE.read_text(encoding="utf-8")
    found = list(_HEAD.finditer(text))
    out = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        out.append((m.group(2), m.group(1).strip(), text[m.end():end].strip()))
    return out


class HelpDialog(QDialog):
    def __init__(self, parent, t: dict, key: str | None = None):
        super().__init__(parent)
        self.setObjectName("wizard")
        self.setWindowTitle("Ajuda — IGNF Finora")
        self.resize(900, 600)
        self.setMinimumSize(620, 400)
        self.items = sections()
        self.list = QListWidget(objectName="contactList")
        self.list.setFixedWidth(210)
        for k, title, _body in self.items:
            it = QListWidgetItem(title)
            it.setData(Qt.UserRole, k)
            it.setSizeHint(QSize(0, 28))
            self.list.addItem(it)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        body = QHBoxLayout()
        body.setSpacing(theme.SP_L)
        body.addWidget(self.list)
        body.addWidget(self.text, 1)
        bottom = QHBoxLayout()
        problem = button("Enviar relatório de problema", "link", t, "fa6s.bug")
        bottom.addWidget(problem)
        bottom.addStretch(1)
        close = button("Fechar", "secondary")
        bottom.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(body, 1)
        lay.addLayout(bottom)
        self.list.currentRowChanged.connect(self._show)
        close.clicked.connect(self.accept)
        problem.clicked.connect(lambda: ProblemDialog(self, t).exec())
        self.select(key)

    def select(self, key: str | None):
        keys = [k for k, _t, _b in self.items]
        self.list.setCurrentRow(keys.index(key) if key in keys else 0)

    def _show(self, row: int):
        if 0 <= row < len(self.items):
            _k, title, body = self.items[row]
            self.text.setMarkdown(f"# {title}\n\n{body}")

    @property
    def current_key(self) -> str:
        return self.items[self.list.currentRow()][0]


class ProblemDialog(QDialog):
    """Junta versão, sistema e o log num .zip e abre o e-mail do suporte para anexar."""

    def __init__(self, parent, t: dict):
        super().__init__(parent)
        self.setObjectName("wizard")
        self.setWindowTitle("Enviar relatório de problema")
        self.setMinimumWidth(480)
        self.path: Path | None = None
        self.folder = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))   # onde salvar
        info = QLabel("O Finora junta num arquivo .zip as informações técnicas (versão, sistema e o registro de "
                      "erros) para o suporte entender o problema. <b>Seus lançamentos, valores e senhas não vão "
                      "junto.</b>", wordWrap=True)
        self.what = QPlainTextEdit(placeholderText="O que aconteceu? O que você estava fazendo? (opcional)")
        self.what.setFixedHeight(110)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancelar", "secondary")
        self.ok = button("Gerar e abrir o e-mail", "primary", t, "fa6s.paper-plane", "on_acc")
        btns.addWidget(cancel)
        btns.addWidget(self.ok)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(info)
        lay.addWidget(self.what)
        lay.addLayout(btns)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.generate)

    def generate(self, open_apps: bool = True):
        from finora.core import db, logs
        from finora.core.licensing import current_edition
        from finora.services import support
        folder = self.folder
        extra = {"Edição": current_edition().value, "Dados": db.describe()}
        try:
            self.path = support.build(folder, logs.LOG_FILE, self.what.toPlainText(), extra)
        except OSError as e:
            QMessageBox.warning(self, "Relatório de problema", f"Não consegui gravar o arquivo: {e}")
            return
        if open_apps:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))
            subject = QUrl.toPercentEncoding(f"Problema no IGNF Finora — {self.path.name}").data().decode()
            body = QUrl.toPercentEncoding(f"Olá! Segue em anexo o arquivo {self.path.name} "
                                          f"(está na pasta {self.path.parent}).\n\n"
                                          f"{self.what.toPlainText()}").data().decode()
            QDesktopServices.openUrl(QUrl(f"mailto:{vendor.EMAIL}?subject={subject}&body={body}"))
        QMessageBox.information(self, "Relatório de problema",
                                f"Pronto! O arquivo foi salvo em:\n{self.path}\n\nAnexe-o no e-mail para "
                                f"{vendor.EMAIL}. Se o e-mail não abriu, envie por lá ou pelo WhatsApp "
                                f"{vendor.PHONE}.")
        self.accept()
