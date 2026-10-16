"""Janela "Levar para outra entidade": escolhe a entidade e a conta de destino dos lançamentos selecionados."""
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout

from finora.core.db import Session
from finora.services import entry_move
from finora.services.entries import EntryView
from finora.ui import theme
from finora.ui.widgets import button, field_label


class MoveDialog(QDialog):
    def __init__(self, parent, rows: list[EntryView], origin_id: int, t: dict):
        super().__init__(parent)
        self.rows = rows
        self.result_info: entry_move.MoveResult | None = None
        self.setObjectName("wizard")
        self.setWindowTitle("Levar para outra entidade")
        self.setMinimumWidth(400)
        with Session() as s:
            self.targets = entry_move.destinations(s, origin_id)

        n = len(rows)
        what = f"\"{rows[0].description}\"" if n == 1 else f"{n} lançamentos"
        info = QLabel(f"Levar {what} para outra entidade. Categoria e contato passam para os de mesmo nome lá; "
                      "o centro de custo, se não for compartilhado, fica em branco.", wordWrap=True)
        self.entity = QComboBox()
        for ent_id, name, _accs in self.targets:
            self.entity.addItem(name, ent_id)
        self.account = QComboBox()
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancelar", "secondary")
        self.ok = button("Levar", "primary")
        btns.addWidget(cancel)
        btns.addWidget(self.ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(info)
        for lbl, w in ((field_label("Entidade de destino", t), self.entity),
                       (field_label("Conta na entidade de destino", t, "De onde sai (ou onde entra) o dinheiro na\n"
                                                                       "entidade de destino."), self.account)):
            box = QVBoxLayout()
            box.setSpacing(3)
            box.addWidget(lbl)
            box.addWidget(w)
            lay.addLayout(box)
        lay.addWidget(self.error)
        lay.addLayout(btns)

        self.entity.currentIndexChanged.connect(self._fill_accounts)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.confirm)
        self._fill_accounts()
        if not self.targets:
            self.error.setText("Não há outra entidade ativa em que você tenha acesso Total ao Financeiro "
                               "e uma conta (que não seja cartão).")
            self.error.show()
            self.ok.setEnabled(False)

    def _fill_accounts(self):
        self.account.clear()
        ent = self.entity.currentData()
        for ent_id, _name, accs in self.targets:
            if ent_id == ent:
                for acc_id, acc_name in accs:
                    self.account.addItem(acc_name, acc_id)

    def confirm(self):
        try:
            with Session() as s:
                self.result_info = entry_move.move_to_entity(s, [e.id for e in self.rows], self.entity.currentData(),
                                                             self.account.currentData())
        except ValueError as err:
            self.error.setText(str(err))
            self.error.show()
            return
        self.accept()
