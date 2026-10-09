"""Tela Administração (mockup): Usuários · Entidades · Permissões · Auditoria."""
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from finora.core import money
from finora.core.db import Session
from finora.core.licensing import LimitError, allowed, current_edition
from finora.services import audit, entity_admin, period_lock, permissions, users
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, field_label, lock_icon, show_upgrade, upgrade_box

PANEL_W = 300
AUDIT_MSG = "O histórico de alterações (quem fez o quê e quando) é um recurso das edições Plus e Pro."
ACTION_ICONS = {"create": "Criou", "update": "Alterou", "delete": "Excluiu", "note": ""}


def _table(headers: list[str], stretch: int) -> QTableWidget:
    tv = QTableWidget(0, len(headers))
    tv.setHorizontalHeaderLabels(headers)
    tv.verticalHeader().hide()
    tv.verticalHeader().setDefaultSectionSize(theme.ROW_H)
    tv.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tv.setSelectionBehavior(QAbstractItemView.SelectRows)
    tv.setSelectionMode(QAbstractItemView.SingleSelection)
    tv.setShowGrid(False)
    tv.setWordWrap(False)
    hdr = tv.horizontalHeader()
    hdr.setHighlightSections(False)
    hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
    hdr.setSectionResizeMode(stretch, QHeaderView.Stretch)
    for i in range(len(headers)):
        tv.horizontalHeaderItem(i).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return tv


def _set_row(tv: QTableWidget, r: int, cells: list[str], data=None, muted: bool = False, t: dict | None = None):
    for c, text in enumerate(cells):
        it = QTableWidgetItem(text)
        if c == 0 and data is not None:
            it.setData(Qt.UserRole, data)
        if muted and t:
            it.setForeground(Qt.gray)
        tv.setItem(r, c, it)


def _form_card(title: QLabel) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame(objectName="card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
    lay.setSpacing(theme.SP_M)
    lay.addWidget(title)
    return card, lay


def _side(widget: QWidget) -> QScrollArea:
    body = QWidget(objectName="pageBody")
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.addWidget(widget)
    bl.addStretch(1)
    sc = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sc.setWidget(body)
    sc.setFixedWidth(PANEL_W)
    return sc


# ---------- Usuários ----------
class UsersTab(QWidget):
    message = Signal(str)

    def __init__(self, t: dict, default_entity: int | None = None):
        super().__init__()
        self.t, self.default_entity = t, default_entity
        self.items: list[users.UserView] = []
        self.editing: users.UserView | None = None
        bar = QHBoxLayout()
        self.count = QLabel()
        self.count.setProperty("role", "field")
        self.new_btn = button("Novo usuário", "secondary", t, "fa6s.plus", "fg")
        bar.addWidget(self.count)
        bar.addStretch(1)
        bar.addWidget(self.new_btn)
        self.table = _table(["NOME", "E-MAIL", "PERFIL", "ENTIDADES", "SENHA", "SITUAÇÃO"], 0)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addLayout(bar)
        left.addWidget(self.table, 1)
        self.hint = QLabel(wordWrap=True)
        self.hint.setProperty("role", "field")
        left.addWidget(self.hint)

        self.title = QLabel(objectName="sectionTitle")
        card, fl = _form_card(self.title)
        self.name = QLineEdit(maxLength=120)
        self.email = QLineEdit(maxLength=120, placeholderText="usado para entrar no app")
        self.is_admin = QCheckBox("Administrador (acesso total a tudo)")
        self.active = QCheckBox("Ativo")
        self.ents = QListWidget()
        self.ents.setMaximumHeight(4 * theme.ROW_H + 6)
        self.pw1 = QLineEdit(echoMode=QLineEdit.Password, placeholderText="mínimo 6 caracteres")
        self.pw2 = QLineEdit(echoMode=QLineEdit.Password, placeholderText="repita a senha")
        self.pw_hint = QLabel(wordWrap=True)
        self.pw_hint.setProperty("role", "field")
        self.remove_pw = QCheckBox("Tirar a senha (o app abre direto)")
        for label, w in (("Nome", self.name), ("E-mail", self.email)):
            fl.addWidget(field_label(label, t))
            fl.addWidget(w)
        fl.addWidget(self.is_admin)
        fl.addWidget(self.active)
        self.ents_lbl = field_label("Entidades que pode abrir", t)
        fl.addWidget(self.ents_lbl)
        fl.addWidget(self.ents)
        fl.addWidget(field_label("Senha", t, "Com senha, o app pede e-mail e senha ao abrir.\n"
                                            "Deixe em branco para manter a senha atual."))
        fl.addWidget(self.pw1)
        fl.addWidget(self.pw2)
        fl.addWidget(self.pw_hint)
        fl.addWidget(self.remove_pw)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        fl.addWidget(self.error)
        row = QHBoxLayout()
        self.save_btn = button("Salvar", "primary")
        self.cancel_btn = button("Cancelar", "secondary")
        row.addWidget(self.save_btn)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        fl.addLayout(row)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SP_L)
        root.addLayout(left, 1)
        root.addWidget(_side(card))
        self.new_btn.clicked.connect(self._new)
        self.cancel_btn.clicked.connect(self._new)
        self.save_btn.clicked.connect(self._save)
        self.table.cellClicked.connect(lambda r, _c: self._edit(self.items[r]) if r < len(self.items) else None)

    def refresh(self):
        with Session() as s:
            self.items = users.list_users(s)
            self._entities = entity_admin.list_entities(s)
        names = {e.id: e.name for e in self._entities}
        lim = users.limit()
        active = sum(1 for u in self.items if u.is_active)
        self.count.setText(f"{active} {'usuário ativo' if active == 1 else 'usuários ativos'}"
                           + (f" de {lim} da sua edição" if lim else ""))
        self.table.setRowCount(len(self.items))
        for r, u in enumerate(self.items):
            ents = ("Todas" if u.is_admin else ", ".join(names.get(e, "?") for e in u.entities) or "Nenhuma")
            _set_row(self.table, r, [u.name, u.email or "—", "Administrador" if u.is_admin else "Usuário", ents,
                                     "Sim" if u.has_password else "Não", "Ativo" if u.is_active else "Inativo"],
                     u.id, not u.is_active, self.t)
        self.hint.setText("Com um usuário só e sem senha, o app abre direto. Para pedir senha ao abrir, informe "
                          "e-mail e senha do seu usuário." if len(self.items) == 1 else
                          "Cada usuário entra com o próprio e-mail e senha. Defina o que cada um vê em Permissões.")
        if self.editing is None:
            self._new()
        else:
            self._edit(next((u for u in self.items if u.id == self.editing.id), self.items[0]))

    def _fill_entities(self, selected: tuple[int, ...]):
        self.ents.clear()
        for e in self._entities:
            it = QListWidgetItem(e.name)
            it.setData(Qt.UserRole, e.id)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if e.id in selected else Qt.Unchecked)
            self.ents.addItem(it)

    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def _new(self):
        self.editing = None
        self.title.setText("Novo usuário")
        for w in (self.name, self.email, self.pw1, self.pw2):
            w.clear()
        self.is_admin.setChecked(False)
        self.active.setChecked(True)
        self.active.hide()
        self._fill_entities((self.default_entity,) if self.default_entity else tuple(e.id for e in self._entities[:1]))
        self.pw_hint.setText("Obrigatória para novos usuários.")
        self.remove_pw.hide()
        self._admin_toggled()
        self._error(None)

    def _edit(self, u: users.UserView):
        self.editing = u
        self.title.setText("Editar usuário")
        self.name.setText(u.name)
        self.email.setText(u.email)
        self.is_admin.setChecked(u.is_admin)
        self.active.setChecked(u.is_active)
        self.active.show()
        self._fill_entities(u.entities)
        self.pw1.clear()
        self.pw2.clear()
        self.pw_hint.setText("Tem senha. Digite uma nova só se quiser trocar." if u.has_password
                             else "Sem senha.")
        self.remove_pw.setChecked(False)
        self.remove_pw.setVisible(u.has_password and len(self.items) == 1)
        self._admin_toggled()
        self._error(None)

    def _admin_toggled(self):
        self.ents.setEnabled(not self.is_admin.isChecked())
        self.ents_lbl.label.setText("Entidades que pode abrir" + (" (administrador: todas)"
                                                                  if self.is_admin.isChecked() else ""))

    def _save(self):
        if self.pw1.text() != self.pw2.text():
            self._error("As duas senhas estão diferentes.")
            return
        ents = [self.ents.item(i).data(Qt.UserRole) for i in range(self.ents.count())
                if self.ents.item(i).checkState() == Qt.Checked]
        try:
            with Session() as s:
                if self.editing is None:
                    if not self.pw1.text():
                        raise ValueError("Defina uma senha para o novo usuário.")
                    uid = users.create(s, name=self.name.text(), email=self.email.text(), password=self.pw1.text(),
                                       is_admin=self.is_admin.isChecked(), entity_ids=ents)
                    msg = "Usuário criado."
                else:
                    uid = self.editing.id
                    users.update(s, uid, name=self.name.text(), email=self.email.text(),
                                 is_admin=self.is_admin.isChecked(), is_active=self.active.isChecked())
                    if not self.is_admin.isChecked():
                        users.set_entities(s, uid, ents)
                    if self.pw1.text():
                        users.set_password(s, uid, self.pw1.text())
                    elif self.remove_pw.isChecked():
                        users.set_password(s, uid, None)
                    msg = "Usuário atualizado."
        except (ValueError, LimitError) as e:
            self._error(str(e))
            return
        self.message.emit(msg)
        self.editing = next((u for u in self.items if u.id == uid), None) or users.UserView(
            uid, "", "", False, True, False, (), None)
        self.refresh()


# ---------- Entidades ----------
class EntitiesTab(QWidget):
    message = Signal(str)
    changed = Signal()

    def __init__(self, t: dict):
        super().__init__()
        self.t = t
        self.items: list[entity_admin.EntityView] = []
        self.editing: entity_admin.EntityView | None = None
        bar = QHBoxLayout()
        self.count = QLabel()
        self.count.setProperty("role", "field")
        self.new_btn = button("Nova entidade", "secondary", t, "fa6s.plus", "fg")
        bar.addWidget(self.count)
        bar.addStretch(1)
        bar.addWidget(self.new_btn)
        self.table = _table(["ENTIDADE", "TIPO", "DOCUMENTO", "MOEDA", "USUÁRIOS", "LANÇAMENTOS", "SITUAÇÃO"], 0)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addLayout(bar)
        left.addWidget(self.table, 1)
        hint = QLabel("Cada entidade (você, sua empresa, um MEI…) tem contas, categorias, lançamentos e relatórios "
                      "totalmente separados. Para trocar de entidade, clique no seu nome no alto do menu.",
                      wordWrap=True)
        hint.setProperty("role", "field")
        left.addWidget(hint)

        self.title = QLabel(objectName="sectionTitle")
        card, fl = _form_card(self.title)
        self.name = QLineEdit(maxLength=120, placeholderText="Ex.: Padaria Sol, Maria (pessoal)")
        self.ptype = QComboBox()
        for k, label in entity_admin.PERSON_TYPES.items():
            self.ptype.addItem(label, k)
        self.doc = QLineEdit(maxLength=18, placeholderText="Opcional")
        self.doc.setFont(theme.mono_font())
        self.currency = QComboBox()
        for code, (_sym, label) in money.CURRENCIES.items():
            self.currency.addItem(f"{code} — {label}", code)
        self.active = QCheckBox("Ativa")
        # logotipo (aparece no menu, no recibo e no cabeçalho dos relatórios)
        logo_row = QHBoxLayout()
        self.logo_view = QLabel(alignment=Qt.AlignCenter, objectName="logoBox")
        self.logo_view.setFixedSize(64, 64)
        self.logo_pick = button("Escolher imagem…", "link", t, "fa6s.image")
        self.logo_clear = button("Remover", "link")
        col = QVBoxLayout()
        col.addWidget(self.logo_pick, 0, Qt.AlignLeft)
        col.addWidget(self.logo_clear, 0, Qt.AlignLeft)
        col.addStretch(1)
        logo_row.addWidget(self.logo_view)
        logo_row.addLayout(col, 1)
        fl.addWidget(field_label("Logotipo", t, "PNG ou JPG. Aparece no menu, no recibo e no cabeçalho dos "
                                               "relatórios.\nImagens grandes são reduzidas sozinhas."))
        fl.addLayout(logo_row)
        self._logo: bytes | None = None
        self._logo_changed = False
        # CPF/CNPJ com "Autopreencher" (dados públicos da Receita, como no cadastro de contatos)
        self.lookup = button("Autopreencher", "secondary", t, "fa6s.wand-magic-sparkles", "acc")
        self.lookup.setToolTip("Busca razão social, telefone, e-mail e endereço do CNPJ na Receita Federal.")
        doc_row = QHBoxLayout()
        doc_row.setSpacing(theme.SP_S)
        doc_row.addWidget(self.doc, 1)
        doc_row.addWidget(self.lookup)
        from finora.core.licensing import allowed, current_edition
        if not allowed(current_edition(), "doc_lookup"):
            from finora.ui.contacts_page import LOOKUP_MSG
            self.lookup.setToolTip(LOOKUP_MSG)
            doc_row.addWidget(lock_icon(LOOKUP_MSG, t))
        for label, w in (("Nome", self.name), ("Tipo", self.ptype), ("CPF/CNPJ", doc_row),
                         ("Moeda principal", self.currency)):
            fl.addWidget(field_label(label, t))
            fl.addLayout(w) if isinstance(w, QHBoxLayout) else fl.addWidget(w)
        self.det = {}
        for key, label, ph in (("document2", "Inscrição estadual/municipal", "Opcional"),
                               ("address", "Endereço", "Rua, número, sala"), ("city", "Cidade", ""),
                               ("state", "UF", "RS"), ("zip_code", "CEP", "95890-000"),
                               ("phone", "Telefone / WhatsApp", ""), ("email", "E-mail", ""),
                               ("website", "Site", "www.exemplo.com.br")):
            w = QLineEdit(maxLength=entity_admin.DETAILS[key], placeholderText=ph)
            self.det[key] = w
            fl.addWidget(field_label(label, t))
            fl.addWidget(w)
        self.det["state"].setMaximumWidth(60)
        self.cep_btn = button("Buscar CEP", "link", t, "fa6s.magnifying-glass")
        self.cep_btn.setToolTip("Preenche endereço, cidade e UF pelo CEP")
        fl.addWidget(self.cep_btn, 0, Qt.AlignLeft)
        self.lookup_note = QLabel(wordWrap=True)
        self.lookup_note.setProperty("role", "field")
        self.lookup_note.hide()
        fl.addWidget(self.lookup_note)
        self.lookup.clicked.connect(self._lookup)
        self.cep_btn.clicked.connect(self._lookup_cep)
        fl.addWidget(self.active)
        self.logo_pick.clicked.connect(self._pick_logo)
        self.logo_clear.clicked.connect(lambda: self._set_logo(None))
        self.lock_info = QLabel(wordWrap=True)
        self.lock_info.setProperty("role", "field")
        fl.addWidget(self.lock_info)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        fl.addWidget(self.error)
        row = QHBoxLayout()
        self.save_btn = button("Salvar", "primary")
        self.cancel_btn = button("Cancelar", "secondary")
        row.addWidget(self.save_btn)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        fl.addLayout(row)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SP_L)
        root.addLayout(left, 1)
        root.addWidget(_side(card))
        self.new_btn.clicked.connect(self._new)
        self.cancel_btn.clicked.connect(self._new)
        self.save_btn.clicked.connect(self._save)
        self.table.cellClicked.connect(lambda r, _c: self._edit(self.items[r]) if r < len(self.items) else None)

    def refresh(self):
        with Session() as s:
            self.items = entity_admin.list_entities(s)
        lim = entity_admin.limit()
        active = sum(1 for e in self.items if e.is_active)
        self.count.setText(f"{active} {'entidade ativa' if active == 1 else 'entidades ativas'}"
                           + (f" de {lim} da sua edição" if lim else ""))
        self.table.setRowCount(len(self.items))
        for r, e in enumerate(self.items):
            _set_row(self.table, r, [e.name, e.person_type, e.document_fmt or "—", e.currency, str(e.users),
                                     str(e.entries), "Ativa" if e.is_active else "Inativa"], e.id, not e.is_active,
                     self.t)
        if self.editing is None:
            self._new()
        else:
            self._edit(next((e for e in self.items if e.id == self.editing.id), self.items[0]))

    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def _new(self):
        self.editing = None
        self.title.setText("Nova entidade")
        self.name.clear()
        self.doc.clear()
        self.lookup_note.hide()
        self.ptype.setCurrentIndex(0)
        self.currency.setEnabled(True)
        self.active.hide()
        for w in self.det.values():
            w.clear()
        self._set_logo(None, changed=False)
        self.lock_info.setText("Vem com uma conta e as categorias padrão. Os administradores já ganham acesso.")
        self._error(None)

    def _edit(self, e: entity_admin.EntityView):
        self.editing = e
        self.title.setText("Editar entidade")
        self.name.setText(e.name)
        self.ptype.setCurrentIndex(max(0, self.ptype.findData(e.person_type)))
        self.doc.setText(e.document_fmt)
        self.lookup_note.hide()
        self.currency.setCurrentIndex(max(0, self.currency.findData(e.currency)))
        self.currency.setEnabled(False)
        self.currency.setToolTip("A moeda principal muda em Configurações › Seu perfil, com a entidade aberta.")
        self.active.setChecked(e.is_active)
        self.active.show()
        with Session() as s:
            lock = period_lock.locked_through(s, e.id)
            det = entity_admin.details(s, e.id)
            logo = entity_admin.get_logo(s, e.id)
        for k, w in self.det.items():
            w.setText(det.get(k, ""))
        self._set_logo(logo, changed=False)
        self.lock_info.setText(f"Período fechado até {lock:%d/%m/%Y}." if lock else "Nenhum período fechado.")
        self._error(None)

    def _set_logo(self, png: bytes | None, changed: bool = True):
        self._logo, self._logo_changed = png, changed
        pix = logo_pixmap(png, 60)
        if pix is not None:
            self.logo_view.setPixmap(pix)
        else:
            self.logo_view.setPixmap(QPixmap())
            self.logo_view.setText("sem\nlogo")
        self.logo_clear.setVisible(png is not None)

    def _lookup(self):
        from finora.core import documents
        from finora.core.licensing import allowed, current_edition
        from finora.services import doc_lookup
        from finora.ui.contacts_page import LOOKUP_MSG, _busy
        if not allowed(current_edition(), "doc_lookup"):
            show_upgrade(self, LOOKUP_MSG)
            return
        if self.ptype.currentData() == "PF" and len(documents.digits(self.doc.text())) != 14:
            self._lookup_msg("CPF não tem consulta pública (são dados pessoais). Para empresa, escolha o tipo PJ "
                             "e digite o CNPJ.", error=True)
            return
        try:
            with _busy():
                data = doc_lookup.cnpj(self.doc.text())
        except ValueError as e:
            self._lookup_msg(str(e), error=True)
            return
        self.ptype.setCurrentIndex(max(0, self.ptype.findData("PJ")))
        self.doc.setText(documents.fmt(documents.digits(self.doc.text())))
        if not self.name.text().strip():
            self.name.setText(data.trade_name or data.name)
        filled = [k for k, v in data.details.items() if v and k in self.det and not self.det[k].text().strip()]
        for k in filled:
            self.det[k].setText(data.details[k])
        labels = {"phone": "telefone", "email": "e-mail", "zip_code": "CEP", "address": "endereço",
                  "city": "cidade", "state": "UF"}
        note = f"Dados da Receita: {data.name}"
        if data.status and data.status.upper() != "ATIVA":
            note += f" — situação {data.status}"
        if filled:
            note += ". Preenchi: " + ", ".join(labels.get(k, k) for k in filled) + "."
        self._lookup_msg(note + " Confira e clique em Salvar.")

    def _lookup_cep(self):
        from finora.core.licensing import allowed, current_edition
        from finora.services import doc_lookup
        from finora.ui.contacts_page import LOOKUP_MSG, _busy
        if not allowed(current_edition(), "doc_lookup"):
            show_upgrade(self, LOOKUP_MSG)
            return
        try:
            with _busy():
                addr = doc_lookup.cep(self.det["zip_code"].text())
        except ValueError as e:
            self._lookup_msg(str(e), error=True)
            return
        self.det["zip_code"].setText(addr.zip_code)
        for key, value in (("address", addr.address), ("city", addr.city), ("state", addr.state)):
            if value:
                self.det[key].setText(value)
        self._lookup_msg("Endereço preenchido pelo CEP. Complete o número e clique em Salvar.")

    def _lookup_msg(self, text: str, error: bool = False):
        self.lookup_note.setProperty("role", "error" if error else "field")
        self.lookup_note.setText(text)
        self.lookup_note.style().polish(self.lookup_note)
        self.lookup_note.show()

    def _pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logotipo da entidade", "", "Imagens (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            self._set_logo(scaled_png(path))
        except ValueError as e:
            self._error(str(e))

    def _save(self):
        try:
            with Session() as s:
                if self.editing is None:
                    eid = entity_admin.create(s, name=self.name.text(), person_type=self.ptype.currentData(),
                                              document=self.doc.text(), currency=self.currency.currentData())
                    msg = "Entidade criada. Para abri-la, clique no seu nome no alto do menu › Trocar entidade."
                else:
                    eid = self.editing.id
                    entity_admin.update(s, eid, name=self.name.text(), person_type=self.ptype.currentData(),
                                        document=self.doc.text(), is_active=self.active.isChecked())
                    msg = "Entidade atualizada."
                entity_admin.update_details(s, eid, **{k: w.text() for k, w in self.det.items()})
                if self._logo_changed:
                    entity_admin.set_logo(s, eid, self._logo)
        except (ValueError, LimitError) as e:
            self._error(str(e))
            return
        self.message.emit(msg)
        self.changed.emit()
        self.refresh()
        self._edit(next(e for e in self.items if e.id == eid))


def scaled_png(path: str, max_side: int = 512) -> bytes:
    """Lê uma imagem e devolve PNG com no máximo `max_side` px (logotipos enormes ficam leves)."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    img = QImage(path)
    if img.isNull():
        raise ValueError("Não consegui abrir essa imagem. Use PNG ou JPG.")
    if max(img.width(), img.height()) > max_side:
        img = img.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def logo_pixmap(png: bytes | None, size: int):
    from PySide6.QtGui import QPixmap
    pix = QPixmap()
    if not png or not pix.loadFromData(png):
        return None
    return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


# ---------- Permissões ----------
class PermissionsTab(QWidget):
    message = Signal(str)

    def __init__(self, t: dict, default_entity: int | None = None):
        super().__init__()
        self.t, self.default_entity = t, default_entity
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        self.user = QComboBox()
        self.user.setMinimumWidth(200)
        self.entity = QComboBox()
        self.entity.setMinimumWidth(200)
        bar.addWidget(QLabel("Usuário"))
        bar.addWidget(self.user)
        bar.addSpacing(theme.SP_M)
        bar.addWidget(QLabel("Entidade"))
        bar.addWidget(self.entity)
        bar.addStretch(1)
        self.title = QLabel(objectName="sectionTitle")
        self.info = QLabel(wordWrap=True)
        self.info.setProperty("role", "field")
        self.grid = QVBoxLayout()
        self.grid.setSpacing(6)
        card = QFrame(objectName="card")
        card.setMaximumWidth(640)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(theme.SP_L, theme.SP_L, theme.SP_L, theme.SP_L)
        cl.setSpacing(theme.SP_M)
        cl.addWidget(self.title)
        cl.addWidget(self.info)
        cl.addLayout(self.grid)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP_L)
        lay.addLayout(bar)
        lay.addWidget(card)
        lay.addStretch(1)
        self.user.currentIndexChanged.connect(self._fill)
        self.entity.currentIndexChanged.connect(self._fill)
        self.groups: dict[str, QButtonGroup] = {}

    def refresh(self):
        with Session() as s:
            us = users.list_users(s, include_inactive=False)
            es = entity_admin.list_entities(s, include_inactive=False)
        for box, items in ((self.user, [(u.id, u.name + (" (administrador)" if u.is_admin else "")) for u in us]),
                           (self.entity, [(e.id, e.name) for e in es])):
            keep = box.currentData() or (self.default_entity if box is self.entity else
                                         next((u.id for u in us if not u.is_admin), None))
            box.blockSignals(True)
            box.clear()
            for i, label in items:
                box.addItem(label, i)
            box.setCurrentIndex(max(0, box.findData(keep)))
            box.blockSignals(False)
        self._fill()

    def _clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                lay = item.layout()
                while lay.count():
                    sub = lay.takeAt(0).widget()
                    if sub:
                        sub.deleteLater()
        self.groups = {}

    def _fill(self):
        self._clear_grid()
        uid, eid = self.user.currentData(), self.entity.currentData()
        if uid is None or eid is None:
            self.title.setText("Permissões")
            self.info.setText("Cadastre usuários em Usuários.")
            return
        with Session() as s:
            u = users.get(s, uid)
            levels = permissions.matrix(s, uid, eid)
            lock = period_lock.locked_through(s, eid)
            has_access = u.is_admin or eid in u.entities
        self.title.setText(f"Permissões · {u.name} em {self.entity.currentText()}")
        notes = []
        if lock:
            notes.append(f"Período fechado até {lock:%d/%m/%Y}.")
        if u.is_admin:
            notes.append("Administrador tem acesso Total a tudo; para limitar, tire o perfil de administrador.")
        elif not has_access:
            notes.append("Esse usuário não abre esta entidade (veja em Usuários › Entidades que pode abrir).")
        self.info.setText(" ".join(notes))
        self.info.setVisible(bool(notes))
        for module, (label, icon, help_text) in permissions.MODULES.items():
            row = QHBoxLayout()
            row.setSpacing(theme.SP_M)
            name = QLabel(label)
            name.setToolTip(help_text)
            name.setMinimumWidth(140)
            row.addWidget(name)
            group = QButtonGroup(self, exclusive=True)
            for i, (lv, lv_label) in enumerate(permissions.LEVELS.items()):
                b = QPushButton(lv_label, checkable=True, checked=levels[module] == lv)
                b.setProperty("variant", "seg")
                b.setProperty("pos", "first" if i == 0 else "last" if i == 2 else "mid")
                b.setProperty("level", lv)
                b.setEnabled(not u.is_admin and has_access)
                b.setMinimumWidth(90)
                group.addButton(b, i)
                row.addWidget(b)
            row.addStretch(1)
            group.idClicked.connect(lambda i, m=module, g=group: self._set(m, g.button(i).property("level")))
            self.groups[module] = group
            self.grid.addLayout(row)

    def _set(self, module: str, value: str):
        try:
            with Session() as s:
                permissions.set_level(s, self.user.currentData(), self.entity.currentData(), module, value)
        except ValueError as e:
            QMessageBox.warning(self, "Permissões", str(e))
            self._fill()
            return
        self.message.emit(f"{permissions.MODULES[module][0]}: {permissions.LEVELS[value]}.")


# ---------- Auditoria ----------
class AuditTab(QWidget):
    def __init__(self, t: dict, profile: Profile):
        super().__init__()
        self.t, self.profile = t, profile
        self.rows: list[audit.AuditView] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.locked = not allowed(current_edition(), "audit")
        if self.locked:
            lay.addWidget(upgrade_box(AUDIT_MSG, t, self))
            lay.addStretch(1)
            return
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP_M)
        self.search = QLineEdit(placeholderText="Buscar no histórico (ex.: Luz, Carlos, baixou)…",
                                clearButtonEnabled=True)
        self.first = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.last = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        today = QDate.currentDate()
        self.first.setDate(today.addDays(-30))
        self.last.setDate(today)
        bar.addWidget(self.search, 1)
        bar.addWidget(QLabel("de"))
        bar.addWidget(self.first)
        bar.addWidget(QLabel("até"))
        bar.addWidget(self.last)
        lay.addLayout(bar)
        self.table = _table(["QUANDO", "QUEM", "O QUE"], 2)
        lay.addWidget(self.table, 1)
        self.details = QPlainTextEdit(readOnly=True)
        self.details.setMaximumHeight(110)
        self.details.setPlaceholderText("Clique numa linha para ver o antes e o depois.")
        lay.addWidget(self.details)
        self.search.textChanged.connect(self.refresh)
        self.first.dateChanged.connect(self.refresh)
        self.last.dateChanged.connect(self.refresh)
        self.table.currentCellChanged.connect(lambda r, *_a: self._show(r))

    def refresh(self):
        if self.locked:
            return
        with Session() as s:
            self.rows = audit.list_log(s, self.profile.id, self.search.text(),
                                       first=self.first.date().toPython(), last=self.last.date().toPython())
        self.table.setRowCount(len(self.rows))
        for r, a in enumerate(self.rows):
            _set_row(self.table, r, [a.at.strftime("%d/%m %H:%M"), a.user, a.summary], a.id)
            self.table.item(r, 0).setFont(theme.mono_font())
        self.details.clear()

    def _show(self, r: int):
        if not 0 <= r < len(self.rows):
            return
        a = self.rows[r]
        lines = [f"{a.at:%d/%m/%Y %H:%M} · {a.user} · {a.summary}"]
        for field, (old, new) in a.changes.items():
            label = audit.FIELDS.get(field, field)
            lines.append(f"  {label}: {old if old is not None else '—'}  →  {new if new is not None else '—'}")
        self.details.setPlainText("\n".join(lines))


# ---------- página ----------
class AdminPage(QWidget):
    message = Signal(str)
    entities_changed = Signal()
    TABS = [("users", "Usuários"), ("entities", "Entidades"), ("permissions", "Permissões"), ("audit", "Auditoria")]

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.tabs = {"users": UsersTab(t, profile.id), "entities": EntitiesTab(t),
                     "permissions": PermissionsTab(t, profile.id),
                     "audit": AuditTab(t, profile)}
        line = QFrame(objectName="tabLine")
        tl = QHBoxLayout(line)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.group = QButtonGroup(self, exclusive=True)
        self.stack = QStackedWidget(objectName="formPages")
        self.tab_buttons = {}
        for i, (key, label) in enumerate(self.TABS):
            b = QPushButton(label, objectName="tabItem", checkable=True, checked=i == 0)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            self.tab_buttons[key] = b
            tl.addWidget(b)
            self.stack.addWidget(self.tabs[key])
            if hasattr(self.tabs[key], "message"):
                self.tabs[key].message.connect(self.message.emit)
        tl.addStretch(1)
        self.tabs["entities"].changed.connect(self.entities_changed.emit)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addWidget(line)
        root.addWidget(self.stack, 1)
        self.group.idClicked.connect(self._select)

    def set_access(self, admin: str, audit_level: str):
        """Sem acesso de administração, só a aba Auditoria (se puder ver)."""
        is_admin = admin == "full"
        for key in ("users", "entities", "permissions"):
            self.tab_buttons[key].setVisible(is_admin)
        self.tab_buttons["audit"].setVisible(audit_level != "none" or is_admin)
        if not is_admin:
            self.tab_buttons["audit"].setChecked(True)
            self.stack.setCurrentWidget(self.tabs["audit"])

    def _select(self, i: int):
        key = self.TABS[i][0]
        self.stack.setCurrentWidget(self.tabs[key])
        self.tabs[key].refresh()

    def refresh(self):
        self.stack.currentWidget().refresh()

    def apply_theme(self, t: dict):
        self.t = t
        for tab in self.tabs.values():
            tab.t = t
