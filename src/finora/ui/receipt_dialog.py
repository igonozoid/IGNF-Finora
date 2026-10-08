"""Janela do recibo: completar os dados, ver a prévia, imprimir ou salvar em PDF."""
from html import escape
from pathlib import Path

from PySide6.QtCore import QDate, QMarginsF, QStandardPaths, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QCheckBox, QDateEdit, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QTextBrowser,
    QVBoxLayout,
)

from finora.core import settings
from finora.core.db import Session
from finora.core.logs import log
from finora.services import receipts
from finora.services.entity_admin import letterhead
from finora.services.export import LOGO_URL, letterhead_html
from finora.services.receipts import Receipt
from finora.ui import theme
from finora.ui.widgets import button, field_label




def receipt_html(r: Receipt, copies: int = 2) -> str:
    """HTML do recibo no formato do IgnControl (preto no branco: é papel, não segue o tema da tela).
    O logotipo entra como recurso do documento (ver add_logo)."""
    h = r.head

    def field(label: str, value: str, italic: bool = False) -> str:
        style = "font-size:9pt; font-style:italic" if italic else "font-size:10pt"
        return (f'<p style="{style}; margin:0 0 5px 0"><span style="color:#374151">{escape(label)}:</span> '
                f'{escape(value or "-")}</p>')

    def one(via: int) -> str:
        tag = (f'<p align="right" style="font-size:7pt; color:#6b7280; margin:0">{via}ª via</p>'
               if copies > 1 else "")
        sign_doc = (f'<br><span style="font-size:7.5pt; color:#6b7280">CPF/CNPJ: {escape(r.signer_doc)}</span>'
                    if r.signer_doc else "")
        return f"""
        <table width="100%" cellspacing="0" cellpadding="10" style="border:1px solid #9ca3af"><tr><td>
          {tag}
          {letterhead_html(h)}
          <p align="center" style="font-size:14pt; font-weight:bold; letter-spacing:2px; margin:4px 0 0 0">RECIBO</p>
          <p align="center" style="font-size:8.5pt; color:#374151; margin:2px 0 10px 0">Data: {r.date_text} | Documento: {escape(r.document or "-")}</p>
          {field(r.party_label, r.party)}
          {field(r.entity_label, r.entity)}
          <table cellspacing="0" cellpadding="0" style="margin:0 0 5px 0"><tr>
            <td style="font-size:10pt"><b>Valor:</b> {escape(r.amount_text)}</td><td width="60"></td>
            <td style="font-size:10pt">Data: {r.date_text}</td></tr></table>
          {field("Documento", r.document)}
          {field("Importância", r.amount_words, italic=True)}
          {field("Referente a", r.reference)}
          {field("Observação", r.notes)}
          <p align="center" style="margin:22px 0 0 0; font-size:9.5pt">______________________________________________________<br>
            <b>{escape(r.signer.upper())}</b>{sign_doc}</p>
        </td></tr></table>"""

    cut = ('<p align="center" style="color:#9ca3af; font-size:8pt; margin:8px 0">'
           '✂ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -</p>')
    body = cut.join(one(i) for i in range(1, copies + 1))
    return ('<html><body style="font-family:Arial,IBM Plex Sans,Helvetica,sans-serif; color:#111827">'
            f'{body}</body></html>')


def add_logo(doc: QTextDocument, r: Receipt) -> None:
    if r.head.logo:
        img = QImage.fromData(r.head.logo)
        doc.addResource(QTextDocument.ImageResource, QUrl(LOGO_URL), img)


class ReceiptDialog(QDialog):
    def __init__(self, parent, entry_id: int, t: dict):
        super().__init__(parent)
        self.entry_id = entry_id
        self.receipt: Receipt | None = None
        self.setObjectName("wizard")
        self.setWindowTitle("Recibo")
        self.resize(900, 560)
        self.setMinimumSize(700, 440)

        _city, my_doc = settings.get_receipt_defaults()
        with Session() as s:
            info = receipts.parties(s, entry_id)
            head = letterhead(s, self._entity_id(s, entry_id))
        self.when = QDateEdit(QDate(info.when.year, info.when.month, info.when.day), calendarPopup=True,
                              displayFormat="dd/MM/yyyy")
        self.document = QLineEdit(info.document, placeholderText="Nº do boleto, nota… (opcional)")
        self.other_name = QLineEdit(info.contact, placeholderText="Nome completo")
        self.other_doc = QLineEdit(info.contact_doc, placeholderText="Opcional")
        self.reference = QLineEdit(info.reference, placeholderText="Ex.: Faxina de outubro")
        self.notes = QLineEdit(placeholderText="Opcional")
        self.my_doc = QLineEdit(my_doc, placeholderText="Opcional")
        self.two = QCheckBox("2 vias na mesma folha", checked=True)
        for w in (self.my_doc, self.other_doc, self.document):
            w.setFont(theme.mono_font())

        who = "recebeu o pagamento" if info.is_expense else "pagou"
        rows = [(field_label("Data", t), self.when), (field_label("Documento", t), self.document),
                (field_label(f"Quem {who}", t), self.other_name),
                (field_label(f"CPF/CNPJ de quem {who}", t), self.other_doc),
                (field_label("Referente a", t), self.reference), (field_label("Observação", t), self.notes)]
        if not head.document:          # entidade sem CPF/CNPJ cadastrado: dá para informar aqui
            rows.append((field_label("CPF/CNPJ da entidade", t, "Cadastre em Administração › Entidades para não "
                                     "precisar digitar.\nFica guardado para os próximos recibos."), self.my_doc))
        else:
            self.my_doc.hide()
        form = QGridLayout()
        form.setHorizontalSpacing(theme.SP_M)
        form.setVerticalSpacing(3)
        for i, (lbl, w) in enumerate(rows):
            form.addWidget(lbl, 2 * i, 0)
            form.addWidget(w, 2 * i + 1, 0)
        form.addWidget(self.two, 2 * len(rows), 0)
        form.setRowStretch(2 * len(rows) + 1, 1)
        self.signer = QLabel(wordWrap=True)
        self.signer.setProperty("role", "field")
        form.addWidget(self.signer, 2 * len(rows) + 2, 0)

        self.preview = QTextBrowser()
        # A prévia imita o papel (branco), independentemente do tema claro/escuro da tela.
        self.preview.setStyleSheet("QTextBrowser { background: #ffffff; color: #000000; border: 1px solid #c8c8c8; }")
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.setMaximumWidth(220)
        self.error.hide()

        body = QHBoxLayout()
        body.setSpacing(theme.SP_L)
        left = QVBoxLayout()
        left.addLayout(form)
        left.addWidget(self.error)
        body.addLayout(left)
        body.addWidget(self.preview, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.pdf_btn = button("Salvar PDF", "secondary", t, "fa6s.file-pdf", "fg")
        self.print_btn = button("Imprimir", "primary", t, "fa6s.print", "on_acc")
        close = button("Fechar", "secondary")
        btns.addWidget(close)
        btns.addWidget(self.pdf_btn)
        btns.addWidget(self.print_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(body, 1)
        lay.addLayout(btns)

        for w in (self.document, self.my_doc, self.other_name, self.other_doc, self.reference, self.notes):
            w.textChanged.connect(self._update)
        self.when.dateChanged.connect(self._update)
        self.two.toggled.connect(self._update)
        close.clicked.connect(self.accept)
        self.print_btn.clicked.connect(self._print)
        self.pdf_btn.clicked.connect(self._pdf)
        self._update()

    @staticmethod
    def _entity_id(s, entry_id: int) -> int:
        from finora.models import Entry
        return s.get(Entry, entry_id).entity_id

    def _update(self):
        try:
            with Session() as s:
                self.receipt = receipts.build(
                    s, self.entry_id, when=self.when.date().toPython(), party=self.other_name.text(),
                    party_doc=self.other_doc.text(), document=self.document.text(),
                    reference=self.reference.text(), notes=self.notes.text(), entity_doc=self.my_doc.text())
        except ValueError as e:
            self.receipt = None
            self.error.setText(str(e))
            self.error.show()
            self.preview.clear()
            self.print_btn.setEnabled(False)
            self.pdf_btn.setEnabled(False)
            return
        self.error.hide()
        self.print_btn.setEnabled(True)
        self.pdf_btn.setEnabled(True)
        self.signer.setText(f"Quem assina: {self.receipt.signer}.")
        add_logo(self.preview.document(), self.receipt)
        self.preview.setHtml(receipt_html(self.receipt, 2 if self.two.isChecked() else 1))

    def _document(self, printer: QPrinter | None = None) -> QTextDocument:
        doc = QTextDocument()
        if printer is not None:      # tamanho da página definido = o Qt não imprime o número da página
            doc.setPageSize(printer.pageRect(QPrinter.Point).size())
        add_logo(doc, self.receipt)
        doc.setHtml(receipt_html(self.receipt, 2 if self.two.isChecked() else 1))
        return doc

    def _printer(self) -> QPrinter:
        p = QPrinter(QPrinter.HighResolution)
        p.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(10, 10, 10, 10),
                                    QPageLayout.Millimeter))
        return p

    def _remember(self):
        settings.set_receipt_defaults("", self.my_doc.text().strip())

    def _print(self):
        printer = self._printer()
        if QPrintDialog(printer, self).exec() == QDialog.Accepted:
            self._document(printer).print_(printer)
            self._remember()
            log.info("Recibo %s impresso", self.receipt.number)

    def save_pdf(self, path: str) -> None:
        printer = self._printer()
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        self._document(printer).print_(printer)
        self._remember()
        log.info("Recibo %s salvo em PDF", self.receipt.number)

    def _pdf(self):
        start = Path(settings.get_backup_folder() or
                     QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)) / f"recibo-{self.receipt.number}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Salvar recibo em PDF", str(start), "PDF (*.pdf)")
        if path:
            self.save_pdf(path)
            self.error.hide()
            self.signer.setText(f"Salvo em {path}")
