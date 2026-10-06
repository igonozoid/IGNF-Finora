"""Botões "Excel" e "PDF": pergunta onde salvar e grava a tabela que a tela montou (services/export.Sheet)."""
from datetime import date
from pathlib import Path

from PySide6.QtCore import QMarginsF, QStandardPaths
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from finora.core.logs import log
from finora.services import export
from finora.services.export import Sheet

KINDS = {"xlsx": ("Excel", "Planilha do Excel (*.xlsx)"), "pdf": ("PDF", "PDF (*.pdf)")}
_last_dir: Path | None = None       # lembra a última pasta durante o uso do app


def save_pdf(sheet: Sheet, path: str) -> None:
    landscape = len(sheet.headers) > 6
    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4),
                                      QPageLayout.Landscape if landscape else QPageLayout.Portrait,
                                      QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter))
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    doc = QTextDocument()
    doc.setHtml(export.to_html(sheet))
    doc.print_(printer)


def save(sheet: Sheet, kind: str, path: str) -> None:
    if kind == "xlsx":
        export.to_xlsx(sheet, path)
    else:
        save_pdf(sheet, path)


def run(parent: QWidget, sheet: Sheet | None, kind: str) -> str | None:
    """Pergunta o arquivo e exporta. Devolve o caminho salvo (ou None se cancelou / não havia dados)."""
    global _last_dir
    label, filt = KINDS[kind]
    if sheet is None or not sheet.rows:
        QMessageBox.information(parent, "Exportar", "Não há nada para exportar com os filtros atuais.")
        return None
    folder = _last_dir or Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
    name = export.safe_name(f"{sheet.title} - {sheet.subtitle or f'{date.today():%Y-%m-%d}'}")
    path, _ = QFileDialog.getSaveFileName(parent, f"Exportar para {label}", str(folder / f"{name}.{kind}"), filt)
    if not path:
        return None
    if not path.lower().endswith(f".{kind}"):
        path += f".{kind}"
    try:
        save(sheet, kind, path)
    except PermissionError:
        QMessageBox.warning(parent, "Exportar", "Não deu para gravar o arquivo. Se ele estiver aberto no Excel "
                                                "ou em outro programa, feche-o e tente de novo.")
        return None
    _last_dir = Path(path).parent
    log.info("Exportado %s: %s", label, path)
    return path
