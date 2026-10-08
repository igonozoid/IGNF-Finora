"""Tela de Contatos: lista com filtros por papel e busca + cadastro lateral (mockup "Contatos")."""
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)
import qtawesome as qta

from finora.core import documents
from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.services import contacts, doc_lookup
from finora.services.contacts import ContactView
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.widgets import button, field_label, lock_icon, shared_checkbox, show_upgrade

PANEL_W = 320
STACK_BELOW = 760   # abaixo dessa largura, o cadastro ocupa o lugar da lista
FILTERS = [("all", "Todos")] + [(k, label) for k, (_c, label, _h) in contacts.ROLES.items()]
LOOKUP_MSG = ("Autopreencher pelo CNPJ (dados públicos da Receita Federal) e o endereço pelo CEP é um recurso das "
              "edições Plus e Pro.")


class ContactRow(QWidget):
    def __init__(self, c: ContactView, narrow: bool):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)
        av = QLabel(c.initials, objectName="avatar", alignment=Qt.AlignCenter)
        av.setFixedSize(28, 28)
        lay.addWidget(av)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(c.name, objectName="cardTitle")
        name.setMinimumWidth(1)
        text.addWidget(name)
        sub = QLabel(c.document_fmt or contacts.PERSON_TYPES[c.person_type])
        sub.setProperty("role", "field")
        if c.document:
            sub.setFont(theme.mono_font())
        text.addWidget(sub)
        lay.addLayout(text, 1)
        if c.shared:
            sh = QLabel("Compartilhado")
            sh.setProperty("role", "badge")
            sh.setToolTip("Aparece em todas as entidades")
            lay.addWidget(sh, 0, Qt.AlignVCenter)
        if not narrow:
            for k, (_col, label, _h) in contacts.ROLES.items():
                if k in c.roles:
                    b = QLabel(label)
                    b.setProperty("role", "badge")
                    lay.addWidget(b, 0, Qt.AlignVCenter)
        if c.entries:
            n = QLabel(str(c.entries))
            n.setProperty("role", "field")
            n.setToolTip(f"{c.entries} {'lançamento' if c.entries == 1 else 'lançamentos'}")
            n.setMinimumWidth(18)
            n.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lay.addWidget(n)


class _busy:
    """Cursor de espera durante a consulta na internet."""

    def __enter__(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)

    def __exit__(self, *_exc):
        QApplication.restoreOverrideCursor()


class ContactForm(QFrame):
    saved = Signal(str, int)     # mensagem, id para selecionar (0 = nenhum)
    closed = Signal()

    def __init__(self, profile: Profile, t: dict):
        super().__init__(objectName="card")
        self.profile, self.t = profile, t
        self.current: ContactView | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(theme.SP_M)

        self.title = QLabel(objectName="sectionTitle", wordWrap=True)
        self.sub = QLabel(wordWrap=True)
        self.sub.setProperty("role", "muted")
        lay.addWidget(self.title)
        lay.addWidget(self.sub)

        # Abas: Dados · Endereço · Bancário · Observações (como no mockup)
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        self.tab_group = QButtonGroup(self, exclusive=True)
        self.pages = QStackedWidget(objectName="formPages")
        for i, label in enumerate(("Dados", "Endereço", "Bancário", "Observações")):
            b = QPushButton(label, objectName="tabItem", checkable=True, checked=(i == 0))
            b.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(b, i)
            tabs.addWidget(b)
        tabs.addStretch(1)
        tab_line = QFrame(objectName="tabLine")
        tab_line.setLayout(tabs)
        lay.addWidget(tab_line)
        self.tab_group.idClicked.connect(self.pages.setCurrentIndex)

        dados = QWidget()
        dl = QVBoxLayout(dados)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(theme.SP_M)

        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.type_group = QButtonGroup(self, exclusive=True)
        for i, (k, label) in enumerate(contacts.PERSON_TYPES.items()):
            b = QPushButton(label, checkable=True)
            b.setProperty("variant", "seg")
            b.setProperty("pos", "first" if i == 0 else "last")
            b.setProperty("ptype", k)
            b.setCursor(Qt.PointingHandCursor)
            self.type_group.addButton(b, i)
            seg.addWidget(b, 1)
        dl.addLayout(seg)

        self.doc_lbl = field_label("CPF", t, "Opcional. Ajuda a não cadastrar a mesma pessoa duas vezes.")
        self.doc = QLineEdit(maxLength=18)
        self.doc.setFont(theme.mono_font())
        self.lookup = button("Autopreencher", "secondary", t, "fa6s.wand-magic-sparkles", "acc")
        self.lookup.setToolTip("Busca nome, telefone, e-mail e endereço do CNPJ na Receita Federal.")
        doc_row = QHBoxLayout()
        doc_row.setSpacing(6)
        doc_row.addWidget(self.doc, 1)
        doc_row.addWidget(self.lookup)
        if not allowed(current_edition(), "doc_lookup"):
            self.lookup.setToolTip(LOOKUP_MSG)
            doc_row.addWidget(lock_icon(LOOKUP_MSG, t))
        dl.addWidget(self.doc_lbl)
        dl.addLayout(doc_row)

        self.name = QLineEdit(maxLength=150, placeholderText="Ex.: Enel, Maria (diarista)")
        dl.addWidget(field_label("Nome", t))
        dl.addWidget(self.name)
        self.details: dict[str, QLineEdit] = {}
        self._detail(dl, "phone", "Telefone / WhatsApp", "(11) 98888-1234")
        self._detail(dl, "email", "E-mail", "nome@exemplo.com")

        dl.addWidget(field_label("Papéis", t, "Um mesmo contato pode ter vários papéis.\n"
                                               "Os lançamentos marcam o papel sozinhos: despesa = Eu pago, "
                                               "receita = Me paga."))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.role_btns: dict[str, QPushButton] = {}
        for k, (_col, label, help_text) in contacts.ROLES.items():
            b = QPushButton(label, checkable=True)
            b.setProperty("variant", "chip")
            b.setToolTip(help_text)
            b.setCursor(Qt.PointingHandCursor)
            self.role_btns[k] = b
            chips.addWidget(b)
        chips.addStretch(1)
        dl.addLayout(chips)
        self.shared = shared_checkbox()
        dl.addWidget(self.shared)
        dl.addStretch(1)
        self.pages.addWidget(dados)

        endereco = QWidget()
        el = QVBoxLayout(endereco)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(theme.SP_M)
        self._detail(el, "zip_code", "CEP", "13010-050", mono=True)
        self.cep_btn = button("Buscar endereço pelo CEP", "link", t, "fa6s.magnifying-glass-location", "acc")
        self.cep_btn.clicked.connect(self._lookup_cep)
        el.addWidget(self.cep_btn, 0, Qt.AlignLeft)
        self._detail(el, "address", "Endereço", "Rua, número, complemento")
        city_row = QHBoxLayout()
        city_row.setSpacing(theme.SP_M)
        cbox, sbox = QVBoxLayout(), QVBoxLayout()
        self._detail(cbox, "city", "Cidade", "")
        self._detail(sbox, "state", "UF", "SP")
        self.details["state"].setMaximumWidth(60)
        city_row.addLayout(cbox, 1)
        city_row.addLayout(sbox)
        el.addLayout(city_row)
        el.addStretch(1)
        self.pages.addWidget(endereco)

        banco = QWidget()
        bl = QVBoxLayout(banco)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(theme.SP_M)
        self._detail(bl, "pix_key", "Chave Pix", "CPF, e-mail, telefone ou chave aleatória")
        self._detail(bl, "bank_info", "Banco · agência · conta", "Ex.: Itaú · 0412 · 55210-3")
        hint = QLabel("Útil para pagar o contato ou para conferir um recebimento.", wordWrap=True)
        hint.setProperty("role", "field")
        bl.addWidget(hint)
        bl.addStretch(1)
        self.pages.addWidget(banco)

        obs = QWidget()
        ol = QVBoxLayout(obs)
        ol.setContentsMargins(0, 0, 0, 0)
        self.notes = QPlainTextEdit(placeholderText="Anotações sobre este contato (opcional)")
        self.notes.setMinimumHeight(120)
        ol.addWidget(self.notes)
        self.pages.addWidget(obs)
        lay.addWidget(self.pages)

        self.error = QLabel(wordWrap=True)
        self.error.setProperty("role", "error")
        self.error.hide()
        lay.addWidget(self.error)

        btns = QHBoxLayout()
        self.save_btn = button("Salvar", "primary")
        self.cancel_btn = button("Cancelar", "secondary")
        self.delete_btn = button("Excluir", "danger")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        btns.addStretch(1)
        btns.addWidget(self.delete_btn)
        lay.addLayout(btns)
        lay.addStretch(1)

        self.type_group.idToggled.connect(lambda _i, on: on and self._type_changed())
        self.doc.editingFinished.connect(self._format_doc)
        self.lookup.clicked.connect(self._lookup)
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self.closed.emit)
        self.delete_btn.clicked.connect(self._delete)
        for e in (self.name, self.doc):
            e.returnPressed.connect(self._save)

    def _detail(self, layout, key: str, label: str, placeholder: str, mono: bool = False):
        edit = QLineEdit(maxLength=contacts.DETAILS[key], placeholderText=placeholder)
        if mono:
            edit.setFont(theme.mono_font())
        edit.returnPressed.connect(self._save)
        layout.addWidget(field_label(label, self.t))
        layout.addWidget(edit)
        self.details[key] = edit

    def _details_data(self) -> dict:
        data = {k: e.text() for k, e in self.details.items()}
        data["notes"] = self.notes.toPlainText()
        return data

    def _fill_details(self, c: ContactView | None):
        for k, e in self.details.items():
            e.setText(c.get(k) if c else "")
        self.notes.setPlainText(c.get("notes") if c else "")
        self.tab_group.button(0).setChecked(True)
        self.pages.setCurrentIndex(0)
        self.shared.setChecked(bool(c and c.shared))

    def _ptype(self) -> str:
        return self.type_group.checkedButton().property("ptype")

    def _type_changed(self):
        pf = self._ptype() == "PF"
        self.doc_lbl.label.setText("CPF" if pf else "CNPJ")
        self.doc.setPlaceholderText("000.000.000-00" if pf else "00.000.000/0000-00")

    def _format_doc(self):
        if documents.is_valid(self.doc.text(), self._ptype()):
            self.doc.setText(documents.fmt(self.doc.text()))

    def _lookup(self):
        if not allowed(current_edition(), "doc_lookup"):
            show_upgrade(self, LOOKUP_MSG)
            return
        if self._ptype() == "PF":
            self._error("CPF não tem consulta pública (são dados pessoais). Preencha os dados à mão.")
            return
        try:
            with _busy():
                data = doc_lookup.cnpj(self.doc.text())
        except ValueError as e:
            self._error(str(e))
            return
        self.doc.setText(documents.fmt(documents.digits(self.doc.text())))
        self.name.setText(data.trade_name or data.name)
        filled = self._fill_empty(data.details)
        note = f"Dados da Receita: {data.name}"
        if data.status and data.status.upper() != "ATIVA":
            note += f" — situação {data.status}"
        if filled:
            note += f". Preenchi: {', '.join(filled)}."
        self._error(None)
        self.sub.setText(note)

    def _lookup_cep(self):
        if not allowed(current_edition(), "doc_lookup"):
            show_upgrade(self, LOOKUP_MSG)
            return
        try:
            with _busy():
                addr = doc_lookup.cep(self.details["zip_code"].text())
        except ValueError as e:
            self._error(str(e))
            return
        self._error(None)
        self.details["zip_code"].setText(addr.zip_code)
        for key, value in (("address", addr.address), ("city", addr.city), ("state", addr.state)):
            if value:
                self.details[key].setText(value)
        self.details["address"].setFocus()
        self.details["address"].end(False)

    def _fill_empty(self, details: dict) -> list[str]:
        """Põe os dados nos campos ainda vazios (não apaga o que você já digitou). Devolve o que preencheu."""
        labels = {"phone": "telefone", "email": "e-mail", "zip_code": "CEP", "address": "endereço",
                  "city": "cidade", "state": "UF"}
        filled = []
        for key, value in details.items():
            edit = self.details.get(key)
            if edit is not None and value and not edit.text().strip():
                edit.setText(value)
                filled.append(labels.get(key, key))
        return filled

    def _error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))

    def open_new(self):
        self.current = None
        self.title.setText("Novo contato")
        self.sub.setText("Um único cadastro, vários papéis.")
        self.type_group.button(0).setChecked(True)
        self._type_changed()
        self.doc.clear()
        self.name.clear()
        for b in self.role_btns.values():
            b.setChecked(False)
        self._fill_details(None)
        self.delete_btn.hide()
        self.cancel_btn.show()
        self._error(None)
        self.name.setFocus()

    def open_contact(self, c: ContactView):
        self.current = c
        self.title.setText(c.name)
        if c.entries:
            self.sub.setText(f"{c.entries} {'lançamento' if c.entries == 1 else 'lançamentos'} · "
                             f"o último em {c.last_date.strftime('%d/%m/%Y')}")
        else:
            self.sub.setText("Ainda não aparece em nenhum lançamento.")
        self.type_group.button(list(contacts.PERSON_TYPES).index(c.person_type)).setChecked(True)
        self._type_changed()
        self.doc.setText(c.document_fmt)
        self.name.setText(c.name)
        for k, b in self.role_btns.items():
            b.setChecked(k in c.roles)
        self._fill_details(c)
        self.delete_btn.show()
        self._error(None)

    def _save(self):
        data = dict(name=self.name.text(), person_type=self._ptype(), document=self.doc.text(),
                    roles={k for k, b in self.role_btns.items() if b.isChecked()}, details=self._details_data(),
                    shared=self.shared.isChecked())
        try:
            with Session() as s:
                if self.current is None:
                    cid = contacts.create(s, self.profile.id, **data)
                    msg = f"Contato \"{data['name'].strip()}\" criado."
                else:
                    cid = self.current.id
                    contacts.update(s, cid, **data)
                    msg = f"Contato \"{data['name'].strip()}\" atualizado."
        except ValueError as e:
            self._error(str(e))
            return
        self.saved.emit(msg, cid)

    def _delete(self):
        c = self.current
        if c is None:
            return
        if QMessageBox.question(self, "Excluir contato", f"Excluir \"{c.name}\"?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            with Session() as s:
                contacts.delete(s, c.id)
        except ValueError as e:
            self._error(str(e))
            return
        self.saved.emit(f"Contato \"{c.name}\" excluído.", 0)


class ContactsPage(QWidget):
    message = Signal(str)

    def __init__(self, profile: Profile, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("content")
        self.profile, self.t = profile, t
        self.role = "all"
        self._items: list[ContactView] = []

        self.filter_group = QButtonGroup(self, exclusive=True)
        pills = QHBoxLayout()
        pills.setSpacing(6)
        for i, (k, label) in enumerate(FILTERS):
            b = QPushButton(label, checkable=True, checked=(k == "all"))
            b.setProperty("variant", "pill")
            b.setProperty("role_key", k)
            b.setProperty("label", label)
            b.setCursor(Qt.PointingHandCursor)
            if k != "all":
                b.setToolTip(contacts.ROLES[k][2])
            self.filter_group.addButton(b, i)
            pills.addWidget(b)
        pills.addStretch(1)

        self.search = QLineEdit(placeholderText="Buscar por nome ou documento…", clearButtonEnabled=True)
        self.search.setMaximumWidth(260)
        self.search_icon = self.search.addAction(qta.icon("fa6s.magnifying-glass", color=t["mut"]),
                                                 QLineEdit.LeadingPosition)
        self.new_btn = button("Novo contato", "secondary", t, "fa6s.plus", "fg")
        top = QHBoxLayout()
        top.setSpacing(theme.SP_M)
        top.addWidget(self.search, 1)
        top.addStretch(0)
        top.addWidget(self.new_btn)

        self.list = QListWidget()
        self.list.setObjectName("contactList")
        self.list.setUniformItemSizes(True)
        self.empty = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")

        self.left = QWidget()
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(theme.SP_M)
        ll.addLayout(top)
        ll.addLayout(pills)
        ll.addWidget(self.list, 1)
        ll.addWidget(self.empty, 1)

        self.form = ContactForm(profile, t)
        self.form_scroll = QScrollArea(objectName="pageScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.form_scroll.setWidget(self.form)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, theme.SP_L, 14, theme.SP_L)
        root.setSpacing(theme.SP_L)
        root.addWidget(self.left, 1)
        root.addWidget(self.form_scroll)

        self.filter_group.idClicked.connect(self._filter)
        self.search.textChanged.connect(lambda: self.refresh())
        self.list.currentRowChanged.connect(self._selected)
        self.new_btn.clicked.connect(self._new)
        self.form.saved.connect(self._saved)
        self.form.closed.connect(self._cancel)
        self._editing = False
        self._was_narrow = self._narrow()
        self._arrange()

    # ----- layout -----
    def _narrow(self) -> bool:
        return self.width() < STACK_BELOW

    def _arrange(self):
        narrow = self._narrow()
        show_form = not narrow or self._editing
        self.form_scroll.setVisible(show_form)
        self.left.setVisible(not (narrow and self._editing))
        self.form_scroll.setFixedWidth(max(PANEL_W, self.width() - 28) if narrow else PANEL_W)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._arrange()
        if self._was_narrow != self._narrow():
            self._was_narrow = self._narrow()
            self.refresh()   # recria as linhas com/sem os selos e abre o 1º contato na tela larga

    # ----- dados -----
    def _filter(self, i: int):
        self.role = self.filter_group.button(i).property("role_key")
        self.refresh()

    def refresh(self, select_id: int | None = None):
        if select_id is None and self.form.current is not None:
            select_id = self.form.current.id
        with Session() as s:
            self._items = contacts.list_contacts(s, self.profile.id, self.search.text(),
                                                 None if self.role == "all" else self.role)
            n = contacts.counts(s, self.profile.id)
        for b in self.filter_group.buttons():
            b.setText(f"{b.property('label')} ({n[b.property('role_key')]})")

        self.list.blockSignals(True)  # recarregar a lista não conta como clique do usuário
        self.list.clear()
        narrow = self._narrow()
        row_to_select = -1
        for i, c in enumerate(self._items):
            it = QListWidgetItem(self.list)
            it.setSizeHint(QSize(0, 46))
            self.list.setItemWidget(it, ContactRow(c, narrow))
            if c.id == select_id:
                row_to_select = i
        if row_to_select < 0 and self._items and not narrow and not self._editing:
            row_to_select = 0     # na tela larga, sempre há um contato aberto ao lado
        if row_to_select >= 0:
            self.list.setCurrentRow(row_to_select)
            self.list.scrollToItem(self.list.item(row_to_select))
        self.list.blockSignals(False)

        has = bool(self._items)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            self.empty.setText("Nada encontrado com essa busca." if self.search.text().strip() or self.role != "all"
                               else "Nenhum contato ainda.\nEles aparecem aqui quando você digita um nome num "
                                    "lançamento, ou use \"Novo contato\".")
        if not self._editing:
            if row_to_select >= 0:
                self.form.open_contact(self._items[row_to_select])
            else:
                self.form.open_new()
        self._arrange()

    def select_contact(self, contact_id: int):
        """Abre um contato (vindo da busca global): limpa filtro e busca locais e seleciona-o."""
        self.filter_group.button(0).setChecked(True)
        self.role = "all"
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._editing = False
        self.form.current = None
        self.refresh(select_id=contact_id)
        row = next((i for i, c in enumerate(self._items) if c.id == contact_id), -1)
        if row >= 0:
            self._selected(row)

    def _selected(self, row: int):
        """Clique do usuário numa linha."""
        if 0 <= row < len(self._items):
            self.form.open_contact(self._items[row])
            self._editing = self._narrow()
            self._arrange()

    def _new(self):
        self.list.blockSignals(True)
        self.list.setCurrentRow(-1)
        self.list.blockSignals(False)
        self.form.open_new()
        self._editing = True
        self._arrange()

    def _cancel(self):
        self._editing = False
        if self.form.current is None:
            self.refresh()                          # desistiu de um contato novo
        else:
            self.form.open_contact(self.form.current)   # descarta o que foi digitado
            self._arrange()

    def _saved(self, msg: str, cid: int):
        self.message.emit(msg)
        self._editing = False
        if not cid:
            self.form.current = None
        self.refresh(select_id=cid or None)

    def apply_theme(self, t: dict):
        self.t = t
        self.search_icon.setIcon(qta.icon("fa6s.magnifying-glass", color=t["mut"]))
