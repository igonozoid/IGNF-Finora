"""Imprimir, Excel e PDF de qualquer tabela que a tela montou (services/export.Sheet).

Tudo passa por aqui, para relatórios e listas saírem iguais: cabeçalho da entidade (o mesmo do recibo),
retrato ou paisagem (lembrado por relatório) e margens."""
from datetime import date
from pathlib import Path

from PySide6.QtCore import QMarginsF, QStandardPaths, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from finora.core import current, settings
from finora.core.logs import log
from finora.services import export
from finora.services.export import Sheet

KINDS = {"xlsx": ("Excel", "Planilha do Excel (*.xlsx)"), "pdf": ("PDF", "PDF (*.pdf)")}
MARGIN_MM = 12
_last_dir: Path | None = None       # lembra a última pasta durante o uso do app


def prepare(sheet: Sheet) -> Sheet:
    """Põe o cabeçalho da entidade aberta (se a tela ainda não pôs)."""
    if sheet.head is None and current.current.entity_id:
        from finora.core.db import Session
        from finora.services.entity_admin import letterhead
        with Session() as s:
            sheet.head = letterhead(s, current.current.entity_id)
    return sheet


def landscape(sheet: Sheet) -> bool:
    """O que o usuário escolheu da última vez neste relatório; sem escolha, paisagem quando há muitas colunas."""
    saved = settings.get_print_landscape(sheet.title)
    return len(sheet.headers) > 6 if saved is None else saved


def make_printer(land: bool, mode=QPrinter.HighResolution) -> QPrinter:
    printer = QPrinter(mode)
    printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape if land else QPageLayout.Portrait,
                                      QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM), QPageLayout.Millimeter))
    return printer


def document(sheet: Sheet) -> QTextDocument:
    doc = QTextDocument()
    if sheet.head is not None and sheet.head.logo:
        doc.addResource(QTextDocument.ImageResource, QUrl(export.LOGO_URL), QImage.fromData(sheet.head.logo))
    doc.setHtml(export.to_html(sheet))
    return doc


def save_pdf(sheet: Sheet, path: str, land: bool | None = None) -> None:
    printer = make_printer(landscape(sheet) if land is None else land)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    document(sheet).print_(printer)


def save(sheet: Sheet, kind: str, path: str, land: bool | None = None) -> None:
    if kind == "xlsx":
        export.to_xlsx(sheet, path)
    else:
        save_pdf(sheet, path, land)


def has_rows(parent: QWidget, sheet: Sheet | None, what: str = "exportar") -> bool:
    if sheet is None or not sheet.rows:
        QMessageBox.information(parent, what.capitalize(), f"Não há nada para {what} com os filtros atuais.")
        return False
    return True


def run(parent: QWidget, sheet: Sheet | None, kind: str, land: bool | None = None) -> str | None:
    """Pergunta o arquivo e exporta. Devolve o caminho salvo (ou None se cancelou / não havia dados)."""
    global _last_dir
    label, filt = KINDS[kind]
    if not has_rows(parent, sheet):
        return None
    prepare(sheet)
    folder = _last_dir or Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
    name = export.safe_name(f"{sheet.title} - {sheet.subtitle or f'{date.today():%Y-%m-%d}'}")
    path, _ = QFileDialog.getSaveFileName(parent, f"Exportar para {label}", str(folder / f"{name}.{kind}"), filt)
    if not path:
        return None
    if not path.lower().endswith(f".{kind}"):
        path += f".{kind}"
    try:
        save(sheet, kind, path, land)
    except PermissionError:
        QMessageBox.warning(parent, "Exportar", "Não deu para gravar o arquivo. Se ele estiver aberto no Excel "
                                                "ou em outro programa, feche-o e tente de novo.")
        return None
    _last_dir = Path(path).parent
    log.info("Exportado %s: %s", label, path)
    return path
