"""Lista de categorias com a opção "+ Nova categoria…" no fim: cria ali mesmo, dentro de um grupo, e já seleciona.

Usada no lançamento, no cadastro de item do estoque, na compra e na venda.
"""
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from finora.core.db import Session
from finora.services import categories
from finora.ui import theme
from finora.ui.widgets import button

NEW = -1
NEW_LABEL = "+ Nova categoria…"


def fill(combo: QComboBox, entity_id: int, kind: str, keep: int | None = None, empty: str = "Sem categoria",
         t: dict | None = None) -> None:
    """Preenche com as categorias do tipo (`income`/`expense`), a opção vazia no topo e "Nova categoria" no fim."""
    with Session() as s:
        items = categories.choices(s, entity_id, kind)
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(empty, None)
    for cid, label in items:
        combo.addItem(label, cid)
    combo.addItem(NEW_LABEL, NEW)
    combo.setCurrentIndex(max(0, combo.findData(keep)) if keep is not None else 0)
    combo.blockSignals(False)
    combo.setProperty("cat_entity", entity_id)
    combo.setProperty("cat_kind", kind)
    combo.setProperty("cat_empty", empty)
    combo.setProperty("cat_last", combo.currentIndex())
    if not combo.property("cat_wired"):
        combo.setProperty("cat_wired", True)
        combo.activated.connect(lambda _i, c=combo, tt=t: picked(c, tt))


def picked(combo: QComboBox, t: dict | None = None, name: str | None = None) -> int | None:
    """Escolheu um item: se foi "Nova categoria", abre a janelinha (ou usa `name`, nos testes) e seleciona a
    criada. Devolve o id criado, ou None."""
    if combo.currentData() != NEW:
        combo.setProperty("cat_last", combo.currentIndex())
        return None
    eid, kind = combo.property("cat_entity"), combo.property("cat_kind")
    dlg = NewCategoryDialog(combo.window(), eid, kind, t)
    if name is not None:
        dlg.name.setText(name)
        new_id = dlg.create()
    else:
        new_id = dlg.new_id if dlg.exec() == QDialog.Accepted else None
    if new_id is None:
        combo.setCurrentIndex(combo.property("cat_last") or 0)
        return None
    fill(combo, eid, kind, keep=new_id, empty=combo.property("cat_empty"), t=t)
    return new_id


class NewCategoryDialog(QDialog):
    def __init__(self, parent, entity_id: int, kind: str, t: dict | None = None):
        super().__init__(parent)
        self.entity_id, self.kind = entity_id, kind
        self.new_id: int | None = None
        self.setWindowTitle("Nova categoria de " + ("receita" if kind == "income" else "despesa"))
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(theme.SP_M)
        form = QFormLayout()
        self.name = QLineEdit(maxLength=60, placeholderText="Ex.: Vendas de azeite")
        self.group = QComboBox()
        with Session() as s:
            for g in categories.groups(s, entity_id):
                if g.kind == kind:
                    self.group.addItem(f"{g.name}  ({g.dre_label})", g.id)
        form.addRow("Nome", self.name)
        form.addRow("Dentro do grupo", self.group)
        lay.addLayout(form)
        note = QLabel("O grupo define a linha da DRE. Para criar um grupo novo, use a tela Categorias.", wordWrap=True)
        note.setProperty("role", "field")
        lay.addWidget(note)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancelar", "secondary")
        ok = button("Criar", "primary")
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(lambda: self.create() is not None and self.accept())
        self.name.returnPressed.connect(lambda: self.create() is not None and self.accept())

    def create(self) -> int | None:
        if self.group.currentData() is None:
            self._err("Não há grupo desse tipo. Crie um na tela Categorias.")
            return None
        try:
            with Session() as s:
                self.new_id = categories.create(s, self.entity_id, name=self.name.text(),
                                                parent_id=self.group.currentData())
        except (ValueError, PermissionError) as e:
            self._err(str(e))
            return None
        return self.new_id

    def _err(self, text: str):
        self.error.setText(text)
        self.error.show()
