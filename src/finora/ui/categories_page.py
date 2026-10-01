"""Tela de Categorias: árvore (grupo > subcategoria) com a linha da DRE + painel de edição."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QLineEdit, QComboBox, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QHBoxLayout, QVBoxLayout,
)
import qtawesome as qta

from finora.core.db import Session
from finora.services import categories, dre
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, field_label

DRE_HELP = ("DRE pessoal é o resumo do mês: quanto entrou, quanto saiu em cada área da vida e quanto sobrou.\n"
            "A linha da DRE diz em qual parte desse resumo os valores desta categoria aparecem.")
COL_NAME, COL_CODE, COL_DRE = range(3)


def _group_icon(c: categories.CategoryView) -> tuple[str, str]:
    if c.dre_group == "receitas":
        return "fa6s.arrow-down", "pos"
    if c.dre_group == "investimentos":
        return "fa6s.piggy-bank", "acc"
    return "fa6s.arrow-up", "neg"


class CategoriesPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile = profile
        self.t = t
        self._by_id: dict[int, categories.CategoryView] = {}
        self.mode = "edit"          # edit | new_group | new_child
        self.current: categories.CategoryView | None = None
        self.new_parent: categories.CategoryView | None = None

        # Barra superior
        self.show_inactive = QCheckBox("Mostrar inativas")
        self.new_group_btn = button("Grupo", "secondary", t, "fa6s.plus", "fg")
        self.new_group_btn.setToolTip("Novo grupo de categorias (ex.: Pets)")
        self.new_child_btn = button("Subcategoria", "secondary", t, "fa6s.plus", "fg")
        self.new_child_btn.setToolTip("Nova subcategoria dentro do grupo selecionado")
        self.toggle_btn = button("Inativar", "secondary")
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        bar.addWidget(self.new_group_btn)
        bar.addWidget(self.new_child_btn)
        bar.addWidget(self.toggle_btn)
        bar.addStretch(1)

        # Árvore
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["CATEGORIA", "CÓDIGO", "LINHA DA DRE"])
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(18)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_CODE, QHeaderView.Fixed)
        hdr.setSectionResizeMode(COL_DRE, QHeaderView.Fixed)
        hdr.resizeSection(COL_CODE, 60)
        hdr.resizeSection(COL_DRE, 160)

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addLayout(bar)
        left.addWidget(self.tree, 1)
        left.addWidget(self.show_inactive)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addLayout(left, 1)
        root.addWidget(self._build_panel())

        self.show_inactive.toggled.connect(self.refresh)
        self.tree.currentItemChanged.connect(self._selected)
        self.new_group_btn.clicked.connect(self._new_group)
        self.new_child_btn.clicked.connect(self._new_child)
        self.toggle_btn.clicked.connect(self._toggle)

    # ---------- painel ----------
    def _build_panel(self) -> QFrame:
        panel = QFrame(objectName="card")
        panel.setFixedWidth(260)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(theme.SP_M)

        self.panel_title = QLabel(objectName="sectionTitle", wordWrap=True)
        self.panel_sub = QLabel(wordWrap=True)
        self.panel_sub.setProperty("role", "muted")
        lay.addWidget(self.panel_title)
        lay.addWidget(self.panel_sub)

        self.name_edit = QLineEdit(maxLength=80)
        lay.addWidget(field_label("Nome", self.t))
        lay.addWidget(self.name_edit)

        self.parent_lbl = field_label("Grupo", self.t)
        self.parent_val = QLineEdit(readOnly=True, enabled=False)
        lay.addWidget(self.parent_lbl)
        lay.addWidget(self.parent_val)

        self.dre_box = QComboBox()
        for key, label in dre.GROUPS.items():
            self.dre_box.addItem(label, key)
        self.dre_lbl = field_label("Linha da DRE", self.t, DRE_HELP)
        lay.addWidget(self.dre_lbl)
        lay.addWidget(self.dre_box)
        self.dre_note = QLabel(wordWrap=True)
        self.dre_note.setProperty("role", "field")
        lay.addWidget(self.dre_note)

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)

        btns = QHBoxLayout()
        self.save_btn = button("Salvar", "primary")
        self.cancel_btn = button("Cancelar", "secondary")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        btns.addStretch(1)
        lay.addLayout(btns)
        lay.addStretch(1)

        self.form_widgets = [self.name_edit, self.dre_box, self.save_btn]
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self._cancel)
        self.name_edit.returnPressed.connect(self._save)
        return panel

    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def _show_form(self, title: str, sub: str, name: str, parent: categories.CategoryView | None,
                   dre_group: str | None, dre_editable: bool, cancel: bool):
        self.panel_title.setText(title)
        self.panel_sub.setText(sub)
        self.panel_sub.setVisible(bool(sub))
        self.name_edit.setText(name)
        self.parent_lbl.setVisible(parent is not None)
        self.parent_val.setVisible(parent is not None)
        self.parent_val.setText(parent.name if parent else "")
        self.dre_box.setCurrentIndex(max(0, self.dre_box.findData(dre_group)))
        self.dre_note.setText("" if dre_editable else "Vem do grupo. Para mudar, edite o grupo.")
        self.dre_note.setVisible(not dre_editable)
        self.cancel_btn.setVisible(cancel)
        for w in self.form_widgets:
            w.setEnabled(True)
        self.dre_box.setEnabled(dre_editable)
        self._error(None)

    def _show_empty(self):
        self.mode, self.current = "edit", None
        self._show_form("Nenhuma categoria selecionada", "Escolha uma categoria na lista para editar, "
                        "ou crie um grupo novo.", "", None, None, False, False)
        self.dre_note.hide()
        for w in self.form_widgets:
            w.setEnabled(False)

    def _selected(self, item: QTreeWidgetItem | None, _prev=None):
        c = self._by_id.get(item.data(0, Qt.UserRole)) if item else None
        self.new_child_btn.setEnabled(c is not None)
        self.toggle_btn.setEnabled(c is not None)
        if c is None:
            self._show_empty()
            return
        self.toggle_btn.setText("Inativar" if c.is_active else "Ativar")
        self.toggle_btn.setToolTip("Inativar esconde a categoria das listas, sem apagar nada."
                                   + (" As subcategorias do grupo também são inativadas." if c.parent_id is None else "")
                                   if c.is_active else "Volta a mostrar a categoria nas listas.")
        self.mode, self.current = "edit", c
        parent = self._by_id.get(c.parent_id)
        kind = "Receita" if c.kind == "income" else "Despesa"
        sub = f"Código {c.code} · {kind}" + ("" if c.is_active else " · Inativa")
        self._show_form("Editar grupo" if parent is None else "Editar subcategoria", sub, c.name, parent,
                        c.dre_group, parent is None, False)

    def _new_group(self):
        self.mode, self.new_parent = "new_group", None
        self._show_form("Novo grupo", "Um grupo reúne subcategorias e define a linha da DRE delas.",
                        "", None, "outras", True, True)
        self.name_edit.setFocus()

    def _new_child(self):
        if self.current is None:
            return
        parent = self.current if self.current.parent_id is None else self._by_id[self.current.parent_id]
        self.mode, self.new_parent = "new_child", parent
        self._show_form("Nova subcategoria", "", "", parent, parent.dre_group, False, True)
        self.name_edit.setFocus()

    def _cancel(self):
        self._selected(self.tree.currentItem())

    def _save(self):
        name = self.name_edit.text()
        try:
            with Session() as s:
                if self.mode == "new_group":
                    new_id = categories.create(s, self.profile.id, name=name, dre_group=self.dre_box.currentData())
                    msg = f"Grupo \"{name.strip()}\" criado."
                elif self.mode == "new_child":
                    new_id = categories.create(s, self.profile.id, name=name, parent_id=self.new_parent.id)
                    msg = f"Subcategoria \"{name.strip()}\" criada em {self.new_parent.name}."
                elif self.current is not None:
                    new_id = self.current.id
                    categories.update(s, new_id, name=name,
                                      dre_group=self.dre_box.currentData() if self.current.parent_id is None else None)
                    msg = f"Categoria \"{name.strip()}\" atualizada."
                else:
                    return
        except ValueError as e:
            self._error(str(e))
            return
        self.message.emit(msg)
        self.refresh(select_id=new_id)

    def _toggle(self):
        c = self.current
        if c is None:
            return
        with Session() as s:
            categories.set_active(s, c.id, not c.is_active)
        if c.is_active:
            hint = "" if self.show_inactive.isChecked() else " Para vê-la, marque \"Mostrar inativas\"."
            self.message.emit(f"Categoria \"{c.name}\" inativada.{hint}")
        else:
            self.message.emit(f"Categoria \"{c.name}\" ativada.")
        self.refresh(select_id=c.id)

    # ---------- árvore ----------
    def refresh(self, select_id: int | None = None):
        if select_id is None or isinstance(select_id, bool):
            select_id = self.current.id if self.current else None
        collapsed = {self.tree.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.tree.topLevelItemCount())
                     if not self.tree.topLevelItem(i).isExpanded()}
        with Session() as s:
            roots = categories.tree(s, self.profile.id, self.show_inactive.isChecked())

        self.tree.blockSignals(True)
        self.tree.clear()
        self._by_id = {}
        bold = QFont()
        bold.setBold(True)
        mono = theme.mono_font()
        muted = QBrush(QColor(self.t["mut"]))
        to_select = None
        for g in roots:
            gi = self._item(g, mono, muted)
            for col in (COL_NAME, COL_DRE):
                gi.setFont(col, bold)
            icon, key = _group_icon(g)
            gi.setData(0, Qt.UserRole + 1, f"{icon}|{key}")
            self.tree.addTopLevelItem(gi)
            for c in g.children:
                ci = self._item(c, mono, muted)
                gi.addChild(ci)
                if c.id == select_id:
                    to_select = ci
            gi.setExpanded(g.id not in collapsed)
            if g.id == select_id:
                to_select = gi
        self._paint_icons()
        self.tree.blockSignals(False)

        if to_select is not None:
            self.tree.setCurrentItem(to_select)
            self.tree.scrollToItem(to_select)
        else:
            self.tree.setCurrentItem(None)
            self._selected(None)

    def _item(self, c: categories.CategoryView, mono: QFont, muted: QBrush) -> QTreeWidgetItem:
        self._by_id[c.id] = c
        it = QTreeWidgetItem([c.name + ("" if c.is_active else "  (inativa)"), c.code,
                              c.dre_label if c.parent_id is None else ""])
        it.setData(0, Qt.UserRole, c.id)
        it.setFont(COL_CODE, mono)
        it.setForeground(COL_CODE, muted)
        if not c.is_active:
            for col in range(3):
                it.setForeground(col, muted)
        return it

    def _paint_icons(self):
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            name, key = it.data(0, Qt.UserRole + 1).split("|")
            it.setIcon(COL_NAME, qta.icon(name, color=self.t[key]))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Em janelas estreitas a coluna da DRE sai (o painel ao lado mostra a mesma informação).
        self.tree.setColumnHidden(COL_DRE, self.tree.width() < 440)

    def apply_theme(self, t: dict):
        self.t = t
        self.refresh()
