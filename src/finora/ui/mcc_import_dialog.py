"""Trazer dados do MCC (Fase 2.11): escolher o mcc.db (clone) ou as planilhas CSV do MCC original, ver a prévia com
a conferência, importar.

A prévia importa e confere de verdade, mas desfaz tudo no fim (mapper.preview): o botão Importar só libera quando
os saldos e totais batem com o MCC. A importação faz backup antes e é tudo-ou-nada (mapper.import_safely).
Planilhas: sheets.build_db monta um banco no formato do clone numa pasta temporária e o caminho é o mesmo; a
conferência dos saldos com o rodapé dos extratos aparece nas notas.
"""
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.core.logs import log
from finora.services.mcc_import import conference, mapper, reader, sheets
from finora.ui import theme
from finora.ui.widgets import WrapLabel, button, field_label, help_icon, set_tone

FILTER = "Banco do MCC (*.db);;Todos os arquivos (*)"
CSV_FILTER = "Planilhas do MCC (*.csv);;Todos os arquivos (*)"


def _day(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "—"


def _cell(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return f"{v:%d/%m/%Y}"
    if hasattr(v, "quantize"):
        return money.fmt(v)
    return str(v)


class MccImportDialog(QDialog):
    imported = Signal()                  # gravou: quem abriu atualiza a lista de entidades

    def __init__(self, parent, t: dict):
        super().__init__(parent)
        self.t = t
        self.path: str = ""
        self.mode = "db"                      # db (mcc.db do clone) | sheets (planilhas do MCC original)
        self.sheet_paths: list[str] = []
        self.bundle: sheets.Bundle | None = None
        self.extra_notes: list[str] = []
        self._tmp = tempfile.mkdtemp(prefix="finora-mcc-")
        self.finished.connect(lambda _r: shutil.rmtree(self._tmp, ignore_errors=True))
        self.summary: reader.Summary | None = None
        self.result: mapper.ImportResult | None = None
        self.report: conference.Conference | None = None
        self.done = False
        self.setObjectName("wizard")
        self.setWindowTitle("Trazer dados do MCC")
        self.resize(900, 600)
        self.setMinimumSize(660, 440)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._choose_page())
        self.stack.addWidget(self._check_page())

        self.error = QLabel(wordWrap=True)
        set_tone(self.error, "neg")
        self.back_btn = button("Voltar", "secondary", t, "fa6s.arrow-left", "fg")
        self.export_btn = button("Exportar conferência", "link", t, "fa6s.file-excel")
        self.next_btn = button("Ver prévia", "primary")
        self.close_btn = button("Fechar", "secondary")
        foot = QHBoxLayout()
        foot.addWidget(self.back_btn)
        foot.addWidget(self.export_btn)
        foot.addStretch(1)
        foot.addWidget(self.close_btn)
        foot.addWidget(self.next_btn)
        self.back_btn.clicked.connect(self._back)
        self.export_btn.clicked.connect(self._export)
        self.next_btn.clicked.connect(self._next)
        self.close_btn.clicked.connect(self.reject)

        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        root.setSpacing(theme.SP_M)
        root.addWidget(self.stack, 1)
        root.addWidget(self.error)
        root.addLayout(foot)
        self._update()

    # ---------- passo 1: arquivo e empresas ----------
    def _choose_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_M)
        head = QHBoxLayout()
        head.addWidget(QLabel("1. De onde vêm os dados", objectName="sectionTitle"))
        head.addWidget(help_icon("Banco do MCC: o arquivo mcc.db do clone do MCC (fica na pasta de dados dele).\n"
                                 "Planilhas: os CSV exportados do MCC original — Relatório Analítico de despesas\n"
                                 "e de receitas, saldo de contas, extrato de cada conta, clientes e fornecedores.\n"
                                 "O Finora lê uma cópia: o MCC não é alterado.\n"
                                 "Pode importar de novo depois: o que já veio é atualizado, sem duplicar.", self.t))
        head.addStretch(1)
        lay.addLayout(head)
        row = QHBoxLayout()
        self.pick_btn = button("Banco do MCC (mcc.db)…", "secondary", self.t, "fa6s.database", "fg")
        self.pick_btn.clicked.connect(self._pick)
        self.sheets_btn = button("Planilhas do MCC (CSV)…", "secondary", self.t, "fa6s.file-csv", "fg")
        self.sheets_btn.clicked.connect(self._pick_sheets)
        row.addWidget(self.pick_btn)
        row.addWidget(self.sheets_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.file_lbl = WrapLabel("Nenhum arquivo escolhido")
        self.file_lbl.setProperty("role", "muted")
        lay.addWidget(self.file_lbl)

        # planilhas: a empresa não vem nelas
        self.sheets_box = QWidget()
        grid = QGridLayout(self.sheets_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SP_M)
        grid.setVerticalSpacing(3)
        self.company = QLineEdit(placeholderText="Nome da empresa (conta controle)")
        self.ptype = QComboBox()
        self.ptype.addItem("Pessoa jurídica", "PJ")
        self.ptype.addItem("Pessoa física", "PF")
        self.doc = QLineEdit(placeholderText="Opcional")
        grid.addWidget(field_label("Empresa", self.t), 0, 0)
        grid.addWidget(field_label("Tipo", self.t), 0, 1)
        grid.addWidget(field_label("CNPJ / CPF", self.t), 0, 2)
        grid.addWidget(self.company, 1, 0)
        grid.addWidget(self.ptype, 1, 1)
        grid.addWidget(self.doc, 1, 2)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(2, 1)
        self.company.textChanged.connect(self._update)
        self.sheets_box.hide()
        lay.addWidget(self.sheets_box)
        self.companies_title = QLabel("Empresas para trazer", objectName="sectionTitle")
        lay.addWidget(self.companies_title)
        self.companies_box = QVBoxLayout()
        self.companies_box.setSpacing(theme.SP_S)
        lay.addLayout(self.companies_box)
        self.info = WrapLabel()
        self.info.setProperty("role", "muted")
        lay.addWidget(self.info)
        lay.addStretch(1)
        self.checks: dict[int, QCheckBox] = {}
        return page

    def _pick(self):
        start = str(Path(self.path).parent) if self.path else \
            QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getOpenFileName(self, "Banco do MCC", start, FILTER)
        if path:
            self.load(path)

    def _pick_sheets(self):
        start = str(Path(self.sheet_paths[0]).parent) if self.sheet_paths else \
            QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        paths, _ = QFileDialog.getOpenFileNames(self, "Planilhas do MCC original", start, CSV_FILTER)
        if paths:
            self.load_sheets(paths)

    def load_sheets(self, paths: list[str]):
        """Reconhece os relatórios pelas colunas; a empresa (nome, tipo, documento) é digitada aqui."""
        self.error.clear()
        try:
            bundle = sheets.load(paths)
        except (ValueError, OSError) as e:
            self.error.setText(str(e))
            return
        self.mode, self.sheet_paths, self.bundle, self.path = "sheets", list(paths), bundle, ""
        self._clear_companies()
        kinds = {}
        for s in bundle.sheets:
            kinds.setdefault(s.label, []).append(s.path.name)
        self.file_lbl.setText(f"{len(paths)} planilha(s): " + " · ".join(
            f"{label} ({len(names)})" for label, names in kinds.items()))
        self.info.setText(" ".join(bundle.warnings))
        self.sheets_box.show()
        self.company.setFocus()
        self._update()

    def _clear_companies(self):
        for chk in self.checks.values():
            chk.setParent(None)
        self.checks = {}

    def load(self, path: str):
        """Lê o resumo do banco do MCC e lista as empresas (todas marcadas)."""
        self.error.clear()
        try:
            summary = reader.read_summary(path)
        except (reader.NotMccError, OSError) as e:
            self.error.setText(str(e) or "Não foi possível abrir esse arquivo.")
            return
        self.mode, self.bundle = "db", None
        self.sheets_box.hide()
        self.path, self.summary = path, summary
        self.file_lbl.setText(path)
        self._clear_companies()
        with Session() as s:
            before = mapper.already_imported(s)
        for c in summary.companies:
            text = (f"{c.name} · {c.person_type} · {c.entries} lançamentos · "
                    f"{_day(c.first_day)} a {_day(c.last_day)}")
            if c.id in before:
                text += " · já importada: será atualizada"
            chk = QCheckBox(text, checked=True)
            chk.toggled.connect(self._update)
            self.companies_box.addWidget(chk)
            self.checks[c.id] = chk
        extra = []
        if summary.shared_accounts or summary.shared_people:
            extra.append(f"{summary.shared_accounts} conta(s) e {summary.shared_people} pessoa(s) sem empresa no "
                         "MCC vêm como compartilhadas.")
        if summary.missing_optional:
            extra.append("Tabelas que esse MCC não tem (ficam de fora): " + ", ".join(summary.missing_optional) + ".")
        self.info.setText(" ".join(extra))
        self._update()

    def chosen(self) -> list[int] | None:
        if self.mode == "sheets":
            return None                       # a única empresa das planilhas
        return [cid for cid, chk in self.checks.items() if chk.isChecked()]

    def _build_from_sheets(self) -> bool:
        """Monta o banco das planilhas com a empresa digitada. Refaz a cada prévia (o nome pode ter mudado)."""
        name = self.company.text().strip()
        bundle = sheets.load(self.sheet_paths)
        self.path = str(sheets.build_db(bundle, Path(self._tmp) / "mcc-planilhas.db", company=name,
                                        person_type=self.ptype.currentData(), document=self.doc.text()))
        self.bundle = bundle
        notes = [f"Planilhas: {bundle.entries} lançamento(s); {bundle.paid_dates_found} data(s) de pagamento "
                 f"achada(s) nos extratos; {bundle.transfers} transferência(s)."]
        for c in bundle.balances:
            notes.append(f"Saldo de {c.account}: MCC {money.fmt(c.expected)} · montado {money.fmt(c.rebuilt)}"
                         + ("" if c.ok else " — NÃO BATE"))
        with Session() as s:
            if sheets.company_id(name) in mapper.already_imported(s):
                notes.append(f"\"{name}\" já foi importada das planilhas: o que já veio será atualizado.")
        self.extra_notes = notes + bundle.warnings
        return True

    # ---------- passo 2: prévia e conferência ----------
    def _check_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_M)
        self.status = QLabel(objectName="sectionTitle")
        self.counts = WrapLabel()
        self.problems = WrapLabel()
        set_tone(self.problems, "neg")
        self.notes = WrapLabel()
        self.notes.setProperty("role", "muted")
        self.table = QTableWidget(0, 8)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        for w in (self.status, self.counts, self.problems, self.notes):
            lay.addWidget(w)
        lay.addWidget(self.table, 1)
        return page

    def _show(self, r: mapper.ImportResult, rep: conference.Conference, final: bool):
        self.result, self.report = r, rep
        if final:
            self.status.setText("Importado. A conferência bateu." if rep.ok else
                                "Importado, mas a conferência não bateu — confira abaixo.")
        else:
            self.status.setText("Prévia: tudo bate com o MCC. Nada foi gravado ainda." if rep.ok else
                                "Prévia: há diferenças sem explicação. Nada foi gravado.")
        set_tone(self.status, "pos" if rep.ok else "neg")
        parts = [f"{len(r.entities)} entidade(s)", f"{len(r.accounts)} conta(s)",
                 f"{len(r.cost_centers)} centro(s) de custo", f"{len(r.contacts)} contato(s)",
                 f"{len(r.entries)} lançamento(s)", f"{len(r.movements)} movimentação(ões)",
                 f"{len(r.users)} usuário(s)"]
        text = " · ".join(parts)
        if r.reimport:
            text += f"\nReimportação: {r.created} novo(s), {r.updated} alterado(s), {r.trashed} para a lixeira."
        if final and r.backup:
            text += f"\nBackup de antes da importação: {r.backup.name} (Configurações › Backup)."
        self.counts.setText(text)
        self.problems.setText("\n".join(rep.problems))
        self.problems.setVisible(bool(rep.problems))
        self.notes.setText("\n".join(self.extra_notes + rep.notes + r.warnings))
        sheet = conference.to_sheet(rep)
        self.table.setColumnCount(len(sheet.headers))
        self.table.setHorizontalHeaderLabels([h.upper() for h in sheet.headers])
        self.table.setRowCount(len(sheet.rows))
        for i, (cells, style) in enumerate(zip(sheet.rows, sheet.styles)):
            for j, v in enumerate(cells):
                item = QTableWidgetItem(_cell(v))
                if hasattr(v, "quantize"):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setFont(theme.mono_font())
                if style == "bold":
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.table.setItem(i, j, item)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for j in range(1, len(sheet.headers)):
            hdr.setSectionResizeMode(j, QHeaderView.ResizeToContents)

    def run_preview(self) -> None:
        self.error.clear()
        self.extra_notes = []
        try:
            if self.mode == "sheets":
                self._build_from_sheets()
            with reader.open_copy(self.path) as con, Session() as s:
                days = conference.default_days(con)
                r, rep = mapper.preview(s, con, self.chosen(), days)
        except Exception as e:                              # noqa: BLE001 — mostra o motivo, não derruba a tela
            log.exception("Prévia da importação do MCC")
            self.error.setText(f"A prévia não pôde ser feita: {e}")
            return
        self.done = False
        self._show(r, rep, final=False)
        self.stack.setCurrentIndex(1)
        self._update()

    def run_import(self) -> None:
        self.error.clear()
        try:
            with reader.open_copy(self.path) as con, Session() as s:
                r = mapper.import_safely(s, con, self.chosen())
                rep = conference.build(s, con, r, self.report.days if self.report else None)
        except Exception as e:                              # noqa: BLE001
            log.exception("Importação do MCC")
            self.error.setText(f"A importação não foi feita (nada foi gravado): {e}")
            return
        log.info("MCC importado de %s: %d entidade(s), %d lançamento(s), backup %s", self.path, len(r.entities),
                 len(r.entries), r.backup)
        self.done = True
        self._show(r, rep, final=True)
        self._update()
        self.imported.emit()

    # ---------- navegação ----------
    def _next(self):
        if self.stack.currentIndex() == 0:
            self.run_preview()
        elif self.done:
            self.accept()
        else:
            self.run_import()

    def _back(self):
        self.stack.setCurrentIndex(0)
        self.error.clear()
        self._update()

    def _export(self):
        if self.report is None:
            return
        from finora.ui import exporting
        exporting.run(self, conference.to_sheet(self.report), "xlsx")

    def _update(self):
        first = self.stack.currentIndex() == 0
        self.companies_title.setVisible(bool(self.checks))
        self.back_btn.setVisible(not first and not self.done)
        self.export_btn.setVisible(not first)
        self.close_btn.setVisible(not self.done)
        if first:
            self.next_btn.setText("Ver prévia")
            ready = bool(self.company.text().strip()) if self.mode == "sheets" else bool(self.path and self.chosen())
            self.next_btn.setEnabled(ready)
            self.next_btn.setToolTip("")
        elif self.done:
            self.next_btn.setText("Concluir")
            self.next_btn.setEnabled(True)
            self.next_btn.setToolTip("")
        else:
            ok = bool(self.report and self.report.ok)
            self.next_btn.setText("Importar")
            self.next_btn.setEnabled(ok)
            self.next_btn.setToolTip("" if ok else "A prévia não bateu com o MCC. Exporte a conferência e veja as "
                                                   "diferenças antes de importar.")
