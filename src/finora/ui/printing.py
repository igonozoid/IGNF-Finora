"""Janela "Imprimir" padrão de relatórios e listas: prévia da folha, retrato ou paisagem, imprimir ou salvar em PDF.

Imprimir é de todas as edições; salvar em PDF (e Excel) é das pagas."""
from PySide6.QtGui import QPageLayout
from PySide6.QtPrintSupport import QPrintDialog, QPrintPreviewWidget
from PySide6.QtWidgets import QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from finora.core import settings
from finora.core.licensing import allowed, current_edition
from finora.core.logs import log
from finora.services.export import Sheet
from finora.ui import exporting, theme
from finora.ui.widgets import button, show_upgrade

EXPORT_LOCK = "Salvar em PDF e Excel é um recurso da edição Plus. Imprimir é liberado em todas."


class PrintDialog(QDialog):
    def __init__(self, parent: QWidget, sheet: Sheet, t: dict):
        super().__init__(parent)
        self.sheet = exporting.prepare(sheet)
        self.t = t
        self.saved_path: str | None = None
        self.setObjectName("wizard")
        self.setWindowTitle(f"Imprimir — {sheet.title}")
        self.resize(980, 720)
        self.setMinimumSize(640, 480)
        self.landscape = exporting.landscape(sheet)

        self.printer = exporting.make_printer(self.landscape)
        self.preview = QPrintPreviewWidget(self.printer, self)
        self.preview.paintRequested.connect(lambda p: exporting.document(self.sheet).print_(p))

        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_S)
        bar.addWidget(QLabel("Folha:"))
        self.portrait_btn = self._toggle("Retrato", "fa6s.file")
        self.landscape_btn = self._toggle("Paisagem", "fa6s.file-lines")
        self.orient = QButtonGroup(self, exclusive=True)
        for b in (self.portrait_btn, self.landscape_btn):
            self.orient.addButton(b)
            bar.addWidget(b)
        (self.landscape_btn if self.landscape else self.portrait_btn).setChecked(True)
        bar.addSpacing(theme.SP_L)
        zoom_out = button("", "secondary", t, "fa6s.magnifying-glass-minus", "fg")
        zoom_in = button("", "secondary", t, "fa6s.magnifying-glass-plus", "fg")
        fit = button("Largura da folha", "secondary", t, "fa6s.left-right", "fg")
        zoom_out.setToolTip("Diminuir")
        zoom_in.setToolTip("Aumentar")
        for b in (zoom_out, zoom_in, fit):
            bar.addWidget(b)
        bar.addStretch(1)
        self.pages = QLabel()
        self.pages.setProperty("role", "muted")
        bar.addWidget(self.pages)

        btns = QHBoxLayout()
        btns.addStretch(1)
        close = button("Fechar", "secondary")
        self.can_pdf = bool(allowed(current_edition(), "export"))
        self.pdf_btn = button("Salvar PDF", "secondary", t, "fa6s.file-pdf" if self.can_pdf else "fa6s.lock",
                              "fg" if self.can_pdf else "acc")
        if not self.can_pdf:
            self.pdf_btn.setToolTip(EXPORT_LOCK)
        self.print_btn = button("Imprimir…", "primary", t, "fa6s.print", "on_acc")
        self.print_btn.setDefault(True)
        btns.addWidget(close)
        btns.addWidget(self.pdf_btn)
        btns.addWidget(self.print_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(bar)
        lay.addWidget(self.preview, 1)
        lay.addLayout(btns)

        self.orient.buttonClicked.connect(lambda b: self.set_landscape(b is self.landscape_btn))
        zoom_out.clicked.connect(lambda: self.preview.zoomOut())
        zoom_in.clicked.connect(lambda: self.preview.zoomIn())
        fit.clicked.connect(self.preview.fitToWidth)
        self.preview.previewChanged.connect(self._count)
        close.clicked.connect(self.reject)
        self.print_btn.clicked.connect(self._print)
        self.pdf_btn.clicked.connect(self._pdf)
        self.preview.fitToWidth()

    def _toggle(self, text: str, icon: str) -> QPushButton:
        b = button(text, "secondary", self.t, icon, "fg")
        b.setCheckable(True)
        return b

    def _count(self):
        n = self.preview.pageCount()
        self.pages.setText(f"{n} {'página' if n == 1 else 'páginas'}")

    def set_landscape(self, on: bool):
        self.landscape = on
        self.printer.setPageOrientation(QPageLayout.Landscape if on else QPageLayout.Portrait)
        (self.landscape_btn if on else self.portrait_btn).setChecked(True)
        settings.set_print_landscape(self.sheet.title, on)
        self.preview.updatePreview()

    def _print(self):
        printer = exporting.make_printer(self.landscape)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle(f"Imprimir — {self.sheet.title}")
        if dlg.exec() == QDialog.Accepted:
            exporting.document(self.sheet).print_(printer)
            log.info("Impresso: %s", self.sheet.title)
            self.accept()

    def _pdf(self):
        if not self.can_pdf:
            show_upgrade(self, EXPORT_LOCK)
            return
        self.saved_path = exporting.run(self, self.sheet, "pdf", self.landscape)
        if self.saved_path:
            self.accept()


def open_print(parent: QWidget, sheet: Sheet | None, t: dict) -> str | None:
    """Abre a prévia de impressão. Devolve o caminho se o usuário salvou em PDF por ela."""
    if not exporting.has_rows(parent, sheet, "imprimir"):
        return None
    dlg = PrintDialog(parent, sheet, t)
    dlg.exec()
    return dlg.saved_path
