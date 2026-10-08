"""Tela de Conciliação (mockup "Conciliação"): importa o extrato OFX do banco e casa cada linha com um
lançamento do Finora — confirma o que já existe, cria o que falta, ignora o que não interessa."""
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QCompleter, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
import qtawesome as qta

from finora.core import money
from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.core.logs import log
from finora.services import accounts, categories, contacts, reconcile
from finora.services.reconcile import LineView
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, field_label, help_icon, upgrade_box

LOCK_MSG = ("Importar o extrato do banco (OFX) e conciliar com seus lançamentos é um recurso das edições "
            "Plus e Pro.")
R = Qt.AlignRight | Qt.AlignVCenter
L = Qt.AlignLeft | Qt.AlignVCenter
C_DATE, C_BANK, C_VALUE, C_LINK, C_SYS, C_ACT = range(6)
HELP = ("1. Baixe o extrato (ou a fatura do cartão) no site ou app do banco: OFX (às vezes chamado \"Money\"),\n"
        "   CSV ou Excel. Com planilha, o Finora mostra as colunas para você conferir.\n"
        "2. Escolha a conta e clique em \"Importar extrato\".\n"
        "3. Para cada linha, confirme o lançamento sugerido, crie um novo ou ignore.\n"
        "Linhas já importadas não se repetem, então pode importar o mesmo período de novo sem medo.")


class CreateDialog(QDialog):
    """Criar um lançamento a partir de uma linha do extrato (já vem preenchido com a sugestão)."""

    def __init__(self, parent, line: LineView, entity_id: int, t: dict):
        super().__init__(parent)
        self.setWindowTitle("Criar lançamento do extrato")
        self.setMinimumWidth(380)
        kind = "income" if line.amount > 0 else "expense"
        sug = line.suggestion
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP_M)
        info = QLabel(f"{line.posted:%d/%m/%Y} · {line.memo} · "
                      f"{'Receita' if kind == 'income' else 'Despesa'} de {money.fmt(abs(line.amount))}",
                      wordWrap=True)
        info.setProperty("role", "field")
        lay.addWidget(info)
        self.description = QLineEdit(sug.description if sug else "", maxLength=200)
        lay.addWidget(field_label("Descrição", t))
        lay.addWidget(self.description)
        self.category = QComboBox()
        self.category.addItem("Sem categoria", None)
        with Session() as s:
            for cid, label in categories.choices(s, entity_id, kind):
                self.category.addItem(label, cid)
            names = contacts.names(s, entity_id)
        if sug and sug.category_id:
            self.category.setCurrentIndex(max(0, self.category.findData(sug.category_id)))
        lay.addWidget(field_label("Categoria", t))
        lay.addWidget(self.category)
        self.contact = QLineEdit((sug.contact or "") if sug else "", placeholderText="Opcional")
        comp = QCompleter(names, self.contact)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.contact.setCompleter(comp)
        lay.addWidget(field_label("Contato", t))
        lay.addWidget(self.contact)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancelar", "secondary")
        ok = button("Criar e conciliar", "primary", t, "fa6s.check", "on_acc")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def values(self) -> tuple[str, int | None, str]:
        return self.description.text(), self.category.currentData(), self.contact.text()


class ReconcilePage(QWidget):
    message = Signal(str)
    open_entry = Signal(int)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.rows: list[LineView] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        root.setSpacing(10)
        self.locked = not allowed(current_edition(), "ofx")
        if self.locked:
            root.addWidget(upgrade_box(LOCK_MSG + " Com ela você baixa o extrato no banco e o Finora "
                                       "encontra sozinho o que já foi lançado.", t, self))
            root.addStretch(1)
            return

        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        self.account = QComboBox()
        self.account.setMinimumWidth(180)
        self.account.setToolTip("Conta do banco que você está conciliando")
        bar.addWidget(self.account)
        self.show_group = QButtonGroup(self, exclusive=True)
        self.show_btns = {}
        for i, (k, label) in enumerate((("pending", "Falta conciliar"), ("all", "Todas"))):
            b = QPushButton(label, checkable=True, checked=(i == 0))
            b.setProperty("variant", "pill")
            b.setCursor(Qt.PointingHandCursor)
            self.show_group.addButton(b, i)
            self.show_btns[k] = b
            bar.addWidget(b)
        bar.addWidget(help_icon(HELP, t))
        bar.addStretch(1)
        self.summary = QLabel()
        self.summary.setProperty("role", "field")
        bar.addWidget(self.summary)
        self.import_btn = button("Importar extrato", "primary", t, "fa6s.file-import", "on_acc")
        self.import_btn.setToolTip("Extrato ou fatura em OFX, CSV ou Excel (.xlsx), baixado do site ou app do banco")
        bar.addWidget(self.import_btn)
        root.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["DATA", "NO EXTRATO DO BANCO", "VALOR", "", "NO FINORA", ""])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H + 6)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        for col, mode, w in ((C_DATE, QHeaderView.Fixed, 64), (C_BANK, QHeaderView.Stretch, 0),
                             (C_VALUE, QHeaderView.Fixed, 120), (C_LINK, QHeaderView.Fixed, 28),
                             (C_SYS, QHeaderView.Stretch, 0), (C_ACT, QHeaderView.Fixed, 190)):
            hdr.setSectionResizeMode(col, mode)
            if w:
                hdr.resizeSection(col, w)
        self.table.horizontalHeaderItem(C_VALUE).setTextAlignment(R)
        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.body = QStackedWidget()
        self.body.addWidget(self.table)
        self.body.addWidget(self.empty)
        root.addWidget(self.body, 1)
        self.footer = QLabel(wordWrap=True)
        self.footer.setProperty("role", "field")
        root.addWidget(self.footer)

        self.account.currentIndexChanged.connect(self.refresh)
        self.show_group.idClicked.connect(lambda _i: self.refresh())
        self.import_btn.clicked.connect(self._import)
        self.table.cellDoubleClicked.connect(self._double)

    # ----- dados -----
    def _fill_accounts(self):
        keep = self.account.currentData()
        with Session() as s:
            accs = [a for a in accounts.list_accounts(s, self.profile.id) if a.kind != "card"]
        self.account.blockSignals(True)
        self.account.clear()
        for a in accs:
            self.account.addItem(a.name, a.id)
        if keep is not None and self.account.findData(keep) >= 0:
            self.account.setCurrentIndex(self.account.findData(keep))
        self.account.blockSignals(False)

    def refresh(self):
        if self.locked:
            return
        self._fill_accounts()
        acc = self.account.currentData()
        if acc is None:
            self.rows = []
            self._show_empty("Cadastre uma conta de banco para conciliar.")
            return
        show = "pending" if self.show_btns["pending"].isChecked() else "all"
        with Session() as s:
            self.rows = reconcile.lines(s, self.profile.id, acc, show)
            n = reconcile.counts(s, self.profile.id, acc)
        self.show_btns["pending"].setText(f"Falta conciliar ({n['pending']})")
        total = sum(n.values())
        self.summary.setText(f"{n['matched']} de {total} conciliadas" if total else "")
        self.footer.setText("Verde = ligado a um lançamento · Amarelo = sugestão, confira e confirme · "
                            "Cinza = não achei nada, crie ou ignore. Duplo clique abre o lançamento.")
        if not self.rows:
            self._show_empty("Nenhuma linha do extrato importada nesta conta.\nBaixe o extrato no banco (OFX, CSV ou "
                             "Excel) e clique em \"Importar extrato\"." if not total else "Tudo conciliado nesta conta. 👏")
            return
        self.body.setCurrentWidget(self.table)
        self._fill_table()

    def _show_empty(self, text: str):
        self.empty.setText(text)
        self.body.setCurrentWidget(self.empty)
        self.table.setRowCount(0)

    def _fill_table(self):
        t, cur = self.t, self.profile.currency
        self.table.setRowCount(len(self.rows))
        for r, ln in enumerate(self.rows):
            sug = ln.suggestion

            def item(text, align=L, tone=None, mono=False):
                it = QTableWidgetItem(text)
                it.setTextAlignment(align)
                if tone:
                    it.setForeground(QBrush(QColor(t[tone])))
                if mono:
                    it.setFont(theme.mono_font())
                return it

            self.table.setItem(r, C_DATE, item(ln.posted.strftime("%d/%m"), mono=True))
            bank = item(ln.memo)
            bank.setToolTip(ln.memo)
            self.table.setItem(r, C_BANK, bank)
            self.table.setItem(r, C_VALUE, item(money.fmt(ln.amount, cur), R, "pos" if ln.amount > 0 else None,
                                                mono=True))
            if ln.status == "matched":
                icon, tone, text = "fa6s.link", "pos", ln.linked or "Lançamento"
            elif ln.status == "ignored":
                icon, tone, text = "fa6s.eye-slash", "mut", "Ignorada"
            elif sug and sug.kind == "entry":
                icon, tone, text = "fa6s.wand-magic-sparkles", "acc", (
                    f"Sugestão: {sug.description}" + (f" ({sug.when:%d/%m})" if sug.when else ""))
            else:
                icon, tone, text = "fa6s.plus", "mut", (
                    "Não está no Finora" if not (sug and sug.category)
                    else f"Criar: {sug.description} · {sug.category}")
            link = QTableWidgetItem()
            link.setIcon(qta.icon(icon, color=t[tone]))
            self.table.setItem(r, C_LINK, link)
            sys_item = item(text, tone="acc" if tone == "acc" else "mut" if ln.status != "matched" else None)
            sys_item.setToolTip(text)
            self.table.setItem(r, C_SYS, sys_item)
            self.table.setCellWidget(r, C_ACT, self._actions(ln))

    def _actions(self, ln: LineView) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(4)
        lay.addStretch(1)

        def add(text, slot, variant="link"):
            b = button(text, variant)
            b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        if ln.status == "pending":
            sug = ln.suggestion
            if sug and sug.kind == "entry":
                b = add("Confirmar", lambda: self._confirm(ln), "secondary")
                b.setToolTip("Liga as duas linhas. Se o lançamento estava em aberto, fica pago na data do extrato.")
                add("Criar", lambda: self._create(ln))
            else:
                add("Criar", lambda: self._create(ln), "secondary")
            add("Ignorar", lambda: self._act(reconcile.ignore, ln.id, "Linha ignorada."))
        else:
            add("Desfazer", lambda: self._act(reconcile.undo, ln.id, "Linha voltou para \"falta conciliar\"."))
        return w

    # ----- ações -----
    def _act(self, fn, line_id: int, msg: str):
        try:
            with Session() as s:
                fn(s, line_id)
        except ValueError as e:
            QMessageBox.warning(self, "Conciliação", str(e))
            return
        self.message.emit(msg)
        self.refresh()

    def _confirm(self, ln: LineView):
        try:
            with Session() as s:
                reconcile.confirm(s, ln.id, ln.suggestion.entry_id)
        except ValueError as e:
            QMessageBox.warning(self, "Conciliação", str(e))
            return
        self.message.emit(f"Conciliado: {ln.suggestion.description}")
        self.refresh()

    def _create(self, ln: LineView):
        dlg = CreateDialog(self, ln, self.profile.id, self.t)
        if dlg.exec() != QDialog.Accepted:
            return
        desc, cat, contact = dlg.values()
        try:
            with Session() as s:
                reconcile.create(s, ln.id, desc, cat, contact or None)
        except ValueError as e:
            QMessageBox.warning(self, "Conciliação", str(e))
            return
        self.message.emit("Lançamento criado e conciliado.")
        self.refresh()

    def _double(self, row: int, _col: int):
        if row < len(self.rows):
            ln = self.rows[row]
            entry = ln.entry_id or (ln.suggestion.entry_id if ln.suggestion else None)
            if entry:
                self.open_entry.emit(entry)

    def _import(self):
        acc = self.account.currentData()
        if acc is None:
            QMessageBox.information(self, "Importar extrato", "Cadastre primeiro a conta do banco em Contas.")
            return
        start = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        path, _ = QFileDialog.getOpenFileName(self, f"Extrato da conta {self.account.currentText()}", start,
                                              "Extratos (*.ofx *.OFX *.csv *.CSV *.txt *.xlsx);;OFX (*.ofx *.OFX);;"
                                              "Planilha (*.csv *.txt *.xlsx);;Todos os arquivos (*)")
        if not path:
            return
        self.import_file(path)

    def import_file(self, path: str) -> None:
        acc = self.account.currentData()
        try:
            data = Path(path).read_bytes()
            if path.lower().endswith(".ofx") or data.lstrip()[:20].upper().startswith((b"OFXHEADER", b"<OFX")):
                with Session() as s:
                    r = reconcile.import_ofx(s, self.profile.id, acc, data)
            else:
                lines = self._sheet_lines(path, data)
                if lines is None:
                    return
                with Session() as s:
                    r = reconcile.import_lines(s, self.profile.id, acc, lines)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Importar extrato", str(e) if isinstance(e, ValueError)
                                else "Não consegui abrir o arquivo.")
            return
        log.info("Extrato importado: %s novas, %s repetidas", r.new, r.repeated)
        parts = [f"{r.new} {'linha nova' if r.new == 1 else 'linhas novas'}"]
        if r.repeated:
            parts.append(f"{r.repeated} já importada{'s' if r.repeated != 1 else ''} antes")
        if r.auto_matched:
            parts.append(f"{r.auto_matched} ligada{'s' if r.auto_matched != 1 else ''} sozinha"
                         f"{'s' if r.auto_matched != 1 else ''}")
        self.message.emit(f"Extrato de {r.first:%d/%m} a {r.last:%d/%m}: " + ", ".join(parts) + ".")
        self.show_btns["pending"].setChecked(True)
        self.refresh()

    def _sheet_lines(self, path: str, data: bytes):
        """Planilha (CSV/Excel): mostra as colunas adivinhadas e a prévia. None se cancelou."""
        from finora.services import accounts, statement_import
        from finora.ui.statement_dialog import StatementDialog
        rows = statement_import.read_table(data, Path(path).name)
        with Session() as s:
            acc = next(a for a in accounts.list_accounts(s, self.profile.id, include_inactive=True)
                       if a.id == self.account.currentData())
        dlg = StatementDialog(self, rows, Path(path).name, acc.name, acc.kind == "card", acc.currency, self.t)
        if dlg.exec() != QDialog.Accepted or dlg.parsed is None:
            return None
        return dlg.parsed.lines

    def apply_theme(self, t: dict):
        self.t = t
        if not self.locked and self.isVisible():
            self.refresh()
