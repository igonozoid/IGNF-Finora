"""Quadro "Comprovantes" do formulário de lançamento: anexar, abrir, salvar uma cópia e remover."""
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout, QWidget,
)
import qtawesome as qta

from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.core.logs import log
from finora.services import attachments
from finora.ui import theme
from finora.ui.widgets import button, field_label, lock_icon, show_upgrade

LOCK_MSG = "Anexar comprovantes (foto do recibo, boleto, nota fiscal) é um recurso das edições Plus e Pro."
FILTER = ("Comprovantes (*.pdf *.jpg *.jpeg *.png *.webp *.gif *.heic *.txt *.xml *.csv *.xlsx *.xls *.doc "
          "*.docx *.odt *.ods *.zip);;Todos os arquivos (*)")
OPEN_DIR = Path(tempfile.gettempdir()) / "finora-anexos"


class AttachmentsBox(QWidget):
    changed = Signal(str)          # mensagem para a barra de status

    def __init__(self, t: dict):
        super().__init__()
        self.t = t
        self.entry_id: int | None = None
        self.locked = not allowed(current_edition(), "attachments")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.label = field_label("Comprovantes", t, "Foto do recibo, boleto, nota fiscal… Ficam guardados dentro\n"
                                                    "do Finora e vão junto no backup.")
        if self.locked:
            self.label.layout().insertWidget(1, lock_icon(LOCK_MSG, t))
        lay.addWidget(self.label)
        self.list = QListWidget(objectName="attachList")
        self.list.setIconSize(QSize(12, 12))
        lay.addWidget(self.list)
        self.hint = QLabel(wordWrap=True)
        self.hint.setProperty("role", "field")
        lay.addWidget(self.hint)
        row = QHBoxLayout()
        row.setSpacing(theme.SP_S)
        self.add_btn = button("Anexar…", "secondary", t, "fa6s.paperclip", "fg")
        self.open_btn = button("Abrir", "link")
        self.save_btn = button("Salvar cópia", "link")
        self.remove_btn = button("Remover", "link")
        for b in (self.add_btn, self.open_btn, self.save_btn, self.remove_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.add_btn.clicked.connect(self._add)
        self.open_btn.clicked.connect(self._open)
        self.save_btn.clicked.connect(self._save_copy)
        self.remove_btn.clicked.connect(self._remove)
        self.list.itemDoubleClicked.connect(lambda _i: self._open())
        self.list.currentRowChanged.connect(lambda _r: self._buttons())
        self.set_entry(None)

    # ----- estado -----
    def set_entry(self, entry_id: int | None):
        self.entry_id = entry_id
        self.list.clear()
        if entry_id is not None and not self.locked:
            with Session() as s:
                items = attachments.list_for(s, entry_id)
            icon = qta.icon("fa6s.file", color=self.t["mut"])
            for a in items:
                it = QListWidgetItem(icon, f"{a.filename}  ·  {a.size_label}")
                it.setData(Qt.UserRole, a.id)
                it.setToolTip(f"Anexado em {a.added:%d/%m/%Y}. Dois cliques para abrir.")
                self.list.addItem(it)
        self.list.setVisible(self.list.count() > 0)
        self.list.setFixedHeight(min(4, max(1, self.list.count())) * (theme.ROW_H + 1) + 4)
        if self.locked:
            self.hint.setText("Disponível nas edições Plus e Pro.")
        elif entry_id is None:
            self.hint.setText("Salve o lançamento para anexar comprovantes.")
        else:
            self.hint.setText("" if self.list.count() else "Nenhum comprovante anexado.")
        self.hint.setVisible(bool(self.hint.text()))
        self._buttons()

    def _buttons(self):
        has = self.list.currentRow() >= 0
        self.add_btn.setEnabled(self.locked or self.entry_id is not None)
        for b in (self.open_btn, self.save_btn, self.remove_btn):
            b.setVisible(self.list.count() > 0)
            b.setEnabled(has)

    def _current(self) -> int | None:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    # ----- ações -----
    def _add(self):
        if self.locked:
            show_upgrade(self, LOCK_MSG)
            return
        start = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        path, _ = QFileDialog.getOpenFileName(self, "Anexar comprovante", start, FILTER)
        if path:
            self.add_file(path)

    def add_file(self, path: str):
        try:
            with Session() as s:
                attachments.add(s, self.entry_id, path)
        except ValueError as e:
            QMessageBox.warning(self, "Anexar comprovante", str(e))
            return
        self.set_entry(self.entry_id)
        self.list.setCurrentRow(self.list.count() - 1)
        self.changed.emit(f"Comprovante anexado: {Path(path).name}")

    def _open(self):
        att = self._current()
        if att is None:
            return
        with Session() as s:
            name, _data = attachments.content(s, att)
            path = attachments.save_copy(s, att, OPEN_DIR / f"{att}-{name}")
        log.info("Abrindo anexo %s", path)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.information(self, "Abrir comprovante", f"Não achei um programa para abrir esse arquivo.\n"
                                                               f"Ele foi salvo em {path}")

    def _save_copy(self):
        att = self._current()
        if att is None:
            return
        with Session() as s:
            name, _data = attachments.content(s, att)
        start = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)) / name
        path, _ = QFileDialog.getSaveFileName(self, "Salvar cópia do comprovante", str(start))
        if path:
            with Session() as s:
                attachments.save_copy(s, att, path)
            self.changed.emit(f"Cópia salva em {path}")

    def _remove(self):
        att = self._current()
        if att is None:
            return
        name = self.list.currentItem().text().split("  ·  ")[0]
        if QMessageBox.question(self, "Remover comprovante", f"Remover \"{name}\" deste lançamento?") \
                != QMessageBox.Yes:
            return
        with Session() as s:
            attachments.remove(s, att)
        self.set_entry(self.entry_id)
        self.changed.emit("Comprovante removido.")

    def apply_theme(self, t: dict):
        self.t = t
        self.set_entry(self.entry_id)
