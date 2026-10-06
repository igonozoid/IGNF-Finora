"""Janela do recibo: completar os dados, ver a prévia, imprimir ou salvar em PDF."""
from html import escape
from pathlib import Path

from PySide6.QtCore import QDate, QMarginsF, QStandardPaths
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QCheckBox, QDateEdit, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QTextBrowser,
    QVBoxLayout,
)

from finora.core import settings
from finora.core.db import Session
from finora.core.logs import log
from finora.services import receipts
from finora.services.receipts import Receipt
from finora.ui import theme
from finora.ui.widgets import button, field_label


def receipt_html(r: Receipt, copies: int = 1) -> str:
    """HTML do recibo (preto no branco: é papel, não segue o tema da tela)."""
    def one(via: str) -> str:
        doc = f"<br>{'CNPJ' if len(r.payee_doc) > 14 else 'CPF'} {escape(r.payee_doc)}" if r.payee_doc else ""
        return f"""
        <table width="100%" cellspacing="0" cellpadding="0"><tr>
          <td><span style="font-size:20pt; font-weight:bold; letter-spacing:2px">RECIBO</span><br>
              <span style="font-size:10pt; color:#555">Nº {escape(r.number)}{via}</span></td>
          <td align="right"><table cellpadding="8" style="border:1px solid #000"><tr>
            <td style="font-size:15pt; font-weight:bold; font-family:Consolas,monospace">{escape(r.amount_text)}</td>
          </tr></table></td>
        </tr></table>
        <p style="font-size:12pt; line-height:160%; margin-top:18px">{escape(r.body)}</p>
        <p style="font-size:11pt; margin-top:14px" align="right">{escape(r.place_date)}</p>
        <p align="center" style="margin-top:46px; font-size:11pt">
          ______________________________________________<br><b>{escape(r.payee)}</b>{doc}</p>"""

    if copies == 1:
        body = one("")
    else:
        cut = ('<p align="center" style="color:#888; font-size:9pt; margin:26px 0">'
               '- - - - - - - - - - - - - - - - recorte aqui - - - - - - - - - - - - - - - -</p>')
        body = one(" · 1ª via") + cut + one(" · 2ª via")
    return f'<html><body style="font-family:Arial,Helvetica,sans-serif; color:#000">{body}</body></html>'


class ReceiptDialog(QDialog):
    def __init__(self, parent, entry_id: int, t: dict):
        super().__init__(parent)
        self.entry_id = entry_id
        self.receipt: Receipt | None = None
        self.setObjectName("wizard")
        self.setWindowTitle("Recibo")
        self.resize(900, 560)
        self.setMinimumSize(700, 440)

        city, my_doc = settings.get_receipt_defaults()
        with Session() as s:
            info = receipts.parties(s, entry_id)
        self.city = QLineEdit(city, placeholderText="Ex.: Campinas")
        self.when = QDateEdit(QDate(info.when.year, info.when.month, info.when.day), calendarPopup=True,
                              displayFormat="dd/MM/yyyy")
        self.my_doc = QLineEdit(my_doc, placeholderText="Opcional")
        self.other_name = QLineEdit(info.contact, placeholderText="Nome completo")
        self.other_doc = QLineEdit(info.contact_doc, placeholderText="Opcional")
        i_received = info.i_received
        self.two = QCheckBox("2 vias na mesma folha")
        for w in (self.my_doc, self.other_doc):
            w.setFont(theme.mono_font())

        who = "pagou" if i_received else "recebeu"
        form = QGridLayout()
        form.setHorizontalSpacing(theme.SP_M)
        form.setVerticalSpacing(3)
        rows = [(field_label("Cidade", t), self.city), (field_label("Data", t), self.when),
                (field_label("Seu CPF/CNPJ", t, "Aparece no recibo; fica guardado para os próximos."), self.my_doc),
                (field_label(f"Quem {who}", t), self.other_name),
                (field_label(f"CPF/CNPJ de quem {who}", t), self.other_doc)]
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

        for w in (self.city, self.my_doc, self.other_name, self.other_doc):
            w.textChanged.connect(self._update)
        self.when.dateChanged.connect(self._update)
        self.two.toggled.connect(self._update)
        close.clicked.connect(self.accept)
        self.print_btn.clicked.connect(self._print)
        self.pdf_btn.clicked.connect(self._pdf)
        self._update()

    def _update(self):
        try:
            with Session() as s:
                self.receipt = receipts.build(
                    s, self.entry_id, city=self.city.text(), when=self.when.date().toPython(),
                    my_doc=self.my_doc.text(), contact_name=self.other_name.text(), contact_doc=self.other_doc.text())
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
        self.signer.setText(f"Quem assina: {self.receipt.payee}.")
        self.preview.setHtml(receipt_html(self.receipt, 2 if self.two.isChecked() else 1))

    def _document(self) -> QTextDocument:
        doc = QTextDocument()
        doc.setHtml(receipt_html(self.receipt, 2 if self.two.isChecked() else 1))
        return doc

    def _printer(self) -> QPrinter:
        p = QPrinter(QPrinter.HighResolution)
        p.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(20, 20, 20, 20),
                                    QPageLayout.Millimeter))
        return p

    def _remember(self):
        settings.set_receipt_defaults(self.city.text().strip(), self.my_doc.text().strip())

    def _print(self):
        printer = self._printer()
        if QPrintDialog(printer, self).exec() == QDialog.Accepted:
            self._document().print_(printer)
            self._remember()
            log.info("Recibo %s impresso", self.receipt.number)

    def save_pdf(self, path: str) -> None:
        printer = self._printer()
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        self._document().print_(printer)
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
