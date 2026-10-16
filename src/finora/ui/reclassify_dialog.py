"""Reclassificar subcategorias na DRE em lote (Fase 2.14): escolher o grupo, conferir as sugestões e aplicar."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from finora.core.db import Session
from finora.services import categories, reclassify
from finora.ui import theme
from finora.ui.widgets import button, help_icon, set_tone

COL_ON, COL_NAME, COL_ENTRIES, COL_DEST, COL_WHY = range(5)


class ReclassifyDialog(QDialog):
    def __init__(self, parent, entity_id: int, t: dict, group_id: int | None = None):
        super().__init__(parent)
        self.entity_id, self.t = entity_id, t
        self.outcome: reclassify.Outcome | None = None
        self.rows: list[reclassify.Suggestion] = []
        self.setObjectName("wizard")
        self.setWindowTitle("Reclassificar na DRE")
        self.resize(860, 520)
        self.setMinimumSize(620, 380)

        with Session() as s:
            tree = categories.tree(s, entity_id)
            self.lines = categories.model_groups(s, entity_id)
        self.groups = [g for g in tree if g.own]
        self.group_box = QComboBox()
        for g in self.groups:
            if g.children:
                self.group_box.addItem(f"{g.name}  ({len(g.children)})", g.id)
        mcc = next((g.id for g in self.groups if g.children and g.name.endswith("do MCC")), None)
        start = group_id if group_id is not None and self.group_box.findData(group_id) >= 0 else mcc
        if start is not None:
            self.group_box.setCurrentIndex(self.group_box.findData(start))

        head = QHBoxLayout()
        head.addWidget(QLabel("Subcategorias do grupo", objectName="sectionTitle"))
        head.addWidget(self.group_box, 1)
        head.addWidget(help_icon("Escolha para onde vai cada subcategoria; a linha da DRE vem do grupo.\n"
                                 "O Finora sugere pelas regras automáticas, por uma subcategoria de mesmo nome\n"
                                 "em outro grupo e por palavras do nome. Se o destino já tem uma de mesmo nome,\n"
                                 "as duas viram uma só (lançamentos, regras e orçamento passam juntos).", t))

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "SUBCATEGORIA", "LANÇ.", "VAI PARA", "SUGESTÃO PORQUE"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_H + 4)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        hdr = self.table.horizontalHeader()
        for col, mode in ((COL_ON, QHeaderView.ResizeToContents), (COL_NAME, QHeaderView.Stretch),
                          (COL_ENTRIES, QHeaderView.ResizeToContents), (COL_DEST, QHeaderView.Fixed),
                          (COL_WHY, QHeaderView.Stretch)):
            hdr.setSectionResizeMode(col, mode)
        hdr.resizeSection(COL_DEST, 250)

        self.error = QLabel(wordWrap=True)
        set_tone(self.error, "neg")
        foot = QHBoxLayout()
        self.count = QLabel()
        self.count.setProperty("role", "muted")
        foot.addWidget(self.count)
        foot.addStretch(1)
        cancel = button("Cancelar", "secondary")
        self.apply_btn = button("Aplicar", "primary")
        foot.addWidget(cancel)
        foot.addWidget(self.apply_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        lay.setSpacing(theme.SP_M)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.error)
        lay.addLayout(foot)
        cancel.clicked.connect(self.reject)
        self.apply_btn.clicked.connect(self.apply)
        self.group_box.currentIndexChanged.connect(self.load)
        self.load()

    def _dest_box(self, row: reclassify.Suggestion) -> QComboBox:
        box = QComboBox()
        box.addItem("— fica onde está —", None)
        have = set()
        for g in self.groups:
            if g.kind == row.kind and g.id != row.group_id and g.parent_id is None:
                box.addItem(f"{g.name}  ·  {g.dre_label}", g.id)
                have.add(g.dre_group)
        for line, label in self.lines.items():
            if line not in have and categories.kind_for(line) == row.kind:
                box.addItem(f"{label}  ·  grupo novo", line)
        if row.target is not None:
            box.setCurrentIndex(max(0, box.findData(row.target)))
        return box

    def load(self):
        gid = self.group_box.currentData()
        self.error.clear()
        self.rows = []
        if gid is not None:
            with Session() as s:
                self.rows = reclassify.suggest(s, self.entity_id, gid)
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            chk = QCheckBox(checked=r.target is not None)
            chk.toggled.connect(self._update)
            self.table.setCellWidget(i, COL_ON, chk)
            self.table.setItem(i, COL_NAME, QTableWidgetItem(r.name))
            n = QTableWidgetItem(str(r.entries))
            n.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            n.setFont(theme.mono_font())
            self.table.setItem(i, COL_ENTRIES, n)
            box = self._dest_box(r)
            box.currentIndexChanged.connect(lambda _i, c=chk, b=box: (c.setChecked(b.currentData() is not None),
                                                                       self._update()))
            self.table.setCellWidget(i, COL_DEST, box)
            why = QTableWidgetItem(r.reason or "sem sugestão")
            if not r.reason:
                why.setForeground(self.palette().placeholderText())
            self.table.setItem(i, COL_WHY, why)
        self._update()

    def moves(self) -> dict[int, int | str]:
        out = {}
        for i, r in enumerate(self.rows):
            dest = self.table.cellWidget(i, COL_DEST).currentData()
            if self.table.cellWidget(i, COL_ON).isChecked() and dest is not None:
                out[r.category_id] = dest
        return out

    def _update(self):
        n = len(self.moves())
        self.count.setText(f"{n} de {len(self.rows)} subcategoria(s) vão mudar de grupo" if self.rows else
                           "Nenhum grupo com subcategorias.")
        self.apply_btn.setEnabled(n > 0)

    def apply(self):
        moves = self.moves()
        if not moves:
            return
        try:
            with Session() as s:
                self.outcome = reclassify.reclassify(s, self.entity_id, moves)
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.accept()

    def message(self) -> str:
        o = self.outcome
        if o is None:
            return ""
        text = f"Reclassificadas: {o.moved} mudaram de grupo"
        if o.merged:
            text += f", {o.merged} juntada(s) a uma de mesmo nome ({o.entries} lançamento(s))"
        return text + "."
