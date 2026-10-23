"""Tela de Contatos: lista com filtros por papel e busca + cadastro lateral (mockup "Contatos")."""
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QCompleter, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
import qtawesome as qta

from finora.core import documents, money
from finora.core.db import Session
from finora.core.licensing import allowed, current_edition
from finora.services import contacts, doc_lookup
from finora.services.contacts import ContactView
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.admin_page import logo_pixmap, scaled_png
from finora.ui.attachments_box import AttachmentsBox
from finora.ui.widgets import button, field_label, lock_icon, shared_checkbox, show_upgrade, upgrade_box

PANEL_W = 320
STACK_BELOW = 760   # abaixo dessa largura, o cadastro ocupa o lugar da lista
FILTERS = [("all", "Todos")] + [(k, label) for k, (_c, label, _h) in contacts.ROLES.items()] + \
    [("review", "A revisar")]
FULL_MSG = ("Crédito, contas bancárias, referências, pessoas de contato e anexos do contato são das edições Plus "
            "e Pro.")
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
        if c.needs_review:
            rv = QLabel("A revisar")
            rv.setProperty("role", "badge")
            rv.setProperty("tone", "acc")
            rv.setToolTip("Criado sozinho a partir de um nome (importação do MCC). Confira os dados e salve.")
            lay.addWidget(rv, 0, Qt.AlignVCenter)
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


class RowsTable(QWidget):
    """Lista editável do contato (outras contas, referências, pessoas de contato): uma linha por item."""

    def __init__(self, key: str, t: dict, title: str, help_text: str):
        super().__init__()
        self.key = key
        self.fields = contacts.LISTS[key][1]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(field_label(title, t, help_text), 1)
        self.add_btn = button("Adicionar", "link", t, "fa6s.plus", "acc")
        self.del_btn = button("Remover", "link", t, "fa6s.trash-can", "mut")
        head.addWidget(self.add_btn)
        head.addWidget(self.del_btn)
        lay.addLayout(head)
        self.table = QTableWidget(0, len(self.fields))
        self.table.setHorizontalHeaderLabels([label for _f, label, _n in self.fields])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(110)
        lay.addWidget(self.table)
        self.add_btn.clicked.connect(self.add_row)
        self.del_btn.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))

    def add_row(self, row: dict | None = None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, (f, _label, _n) in enumerate(self.fields):
            value = (row or {}).get(f) or ""
            if f == "kind":
                box = QComboBox()
                for k, v in contacts.REFERENCE_KINDS.items():
                    box.addItem(v, k)
                box.setCurrentIndex(max(0, box.findData(value)))
                self.table.setCellWidget(r, col, box)
            else:
                self.table.setItem(r, col, QTableWidgetItem(value))
        if row is None:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(self.table.item(r, 0))

    def set_rows(self, rows: list[dict]):
        self.table.setRowCount(0)
        for row in rows:
            self.add_row(row)

    def rows(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            row = {}
            for col, (f, _label, _n) in enumerate(self.fields):
                w = self.table.cellWidget(r, col)
                row[f] = w.currentData() if w is not None else (self.table.item(r, col) or QTableWidgetItem()).text()
            out.append(row)
        return out


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
        self.full = bool(allowed(current_edition(), "contacts_full"))     # crédito, listas e anexos
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(theme.SP_M)

        self.title = QLabel(objectName="sectionTitle", wordWrap=True)
        self.sub = QLabel(wordWrap=True)
        self.sub.setProperty("role", "muted")
        lay.addWidget(self.title)
        lay.addWidget(self.sub)

        # Abas: Dados · Endereço · Bancário · Crédito · Observações (como no mockup)
        # em duas linhas: o painel é estreito
        tabs = QGridLayout()
        tabs.setSpacing(0)
        self.tab_group = QButtonGroup(self, exclusive=True)
        self.pages = QStackedWidget(objectName="formPages")
        for i, label in enumerate(("Dados", "Endereço", "Bancário", "Crédito", "Referências", "Anexos",
                                   "Observações")):
            b = QPushButton(label, objectName="tabItem", checkable=True, checked=(i == 0))
            b.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(b, i)
            tabs.addWidget(b, i // 4, i % 4)
        tabs.setColumnStretch(4, 1)
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
        self.doc2_box = QVBoxLayout()
        self.doc2_box.setSpacing(3)
        self._detail(self.doc2_box, "document2", "RG", "Opcional", mono=True)
        dl.addLayout(self.doc2_box)
        self._detail(dl, "phone", "Telefone / WhatsApp", "(11) 98888-1234")
        self._detail(dl, "email", "E-mail", "nome@exemplo.com")
        self._detail(dl, "contact_person", "Pessoa de contato", "Com quem falar (ex.: Ana, financeiro)")
        self.date_edits: dict[str, QLineEdit] = {}
        drow = QHBoxLayout()
        drow.setSpacing(theme.SP_M)
        for key, label, help_text in (
                ("birthday", "Aniversário", "Aparece nos lembretes no dia (ou alguns dias antes, conforme\n"
                                            "Configurações › Lembretes)."),
                ("important_date", "Data importante", "Volta todo ano nos lembretes (ex.: renovação do contrato).")):
            col = QVBoxLayout()
            col.setSpacing(3)
            edit = QLineEdit(placeholderText="dd/mm/aaaa", maxLength=10)
            edit.setFont(theme.mono_font())
            edit.returnPressed.connect(self._save)
            lbl = field_label(label, t, help_text)
            col.addWidget(lbl)
            col.addWidget(edit)
            drow.addLayout(col, 1)
            self.date_edits[key] = edit
            if key == "birthday":
                self.birthday_lbl = lbl
        dl.addLayout(drow)
        self._detail(dl, "important_label", "O que é a data importante", "Ex.: renovação do contrato")

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
        self._detail(el, "district", "Bairro", "")
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
        self._detail(bl, "bank_name", "Banco", "Ex.: 341 - Itaú")
        acc_row = QHBoxLayout()
        acc_row.setSpacing(theme.SP_M)
        abox, cbox = QVBoxLayout(), QVBoxLayout()
        self._detail(abox, "bank_branch", "Agência", "0412", mono=True)
        self._detail(cbox, "bank_account", "Conta", "55210-3", mono=True)
        acc_row.addLayout(abox, 1)
        acc_row.addLayout(cbox, 1)
        bl.addLayout(acc_row)
        self._detail(bl, "bank_holder", "Titular", "Se a conta não for do próprio contato")
        hint = QLabel("Útil para pagar o contato ou para conferir um recebimento.", wordWrap=True)
        hint.setProperty("role", "field")
        bl.addWidget(hint)
        self.banks = RowsTable("banks", t, "Outras contas", "Mais contas do contato, além da de cima.")
        self.banks.setEnabled(self.full)
        if not self.full:
            self.banks.setToolTip(FULL_MSG)
        bl.addWidget(self.banks)
        bl.addStretch(1)
        self.pages.addWidget(banco)
        self.pages.addWidget(self._credit_page(t))
        self.pages.addWidget(self._refs_page(t))
        self.pages.addWidget(self._files_page(t))

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
        self.merge_btn = button("Mesclar…", "secondary", t, "fa6s.code-merge", "fg")
        self.merge_btn.setToolTip("Juntar a este um contato repetido (com outro nome ou escrito diferente)")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        btns.addStretch(1)
        btns.addWidget(self.merge_btn)
        btns.addWidget(self.delete_btn)
        lay.addLayout(btns)
        lay.addStretch(1)

        self.type_group.idToggled.connect(lambda _i, on: on and self._type_changed())
        self.doc.editingFinished.connect(self._format_doc)
        self.lookup.clicked.connect(self._lookup)
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self.closed.emit)
        self.delete_btn.clicked.connect(self._delete)
        self.merge_btn.clicked.connect(self._merge)
        for e in (self.name, self.doc):
            e.returnPressed.connect(self._save)

    def _credit_page(self, t: dict) -> QWidget:
        page = QWidget()
        cl = QVBoxLayout(page)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(theme.SP_M)
        if not self.full:
            cl.addWidget(upgrade_box(FULL_MSG, t, self, compact=True))
        self.credit_limit = QLineEdit(placeholderText="Ex.: 5.000,00")
        self.credit_limit.setFont(theme.mono_font())
        cl.addWidget(field_label("Limite de crédito", t, "Quanto o cliente pode ficar devendo (a receber em aberto).\n"
                                                        "Passou do limite, Vendas e o lançamento a receber avisam."))
        cl.addWidget(self.credit_limit)
        self.credit_checked_on = QLineEdit(placeholderText="dd/mm/aaaa", maxLength=10)
        self.credit_checked_on.setFont(theme.mono_font())
        cl.addWidget(field_label("Crédito consultado em", t, "Data da última consulta (SPC, Serasa, banco…)"))
        cl.addWidget(self.credit_checked_on)
        self.credit_pending = QCheckBox("Tem pendência (nome sujo, protesto, cheque devolvido…)")
        cl.addWidget(self.credit_pending)
        self.credit_pending_where = QLineEdit(maxLength=80, placeholderText="Onde: SPC, Serasa, cartório…")
        cl.addWidget(self.credit_pending_where)
        self.credit_pending.toggled.connect(self.credit_pending_where.setEnabled)
        self.mother_box = QWidget()
        mb = QVBoxLayout(self.mother_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(3)
        self.mother_name = QLineEdit(maxLength=150)
        mb.addWidget(field_label("Nome da mãe", t, "Ajuda a confirmar a pessoa numa consulta de crédito."))
        mb.addWidget(self.mother_name)
        cl.addWidget(self.mother_box)
        row = QHBoxLayout()
        row.setSpacing(theme.SP_M)
        self.rating, self.frequency = QComboBox(), QComboBox()
        for box, choices, label in ((self.rating, contacts.RATINGS, "Classificação"),
                                    (self.frequency, contacts.FREQUENCIES, "Compra com frequência")):
            box.addItem("—", None)
            for k, v in choices.items():
                box.addItem(v, k)
            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(field_label(label, t))
            col.addWidget(box)
            row.addLayout(col, 1)
        cl.addLayout(row)
        cl.addStretch(1)
        for w in (self.credit_limit, self.credit_checked_on, self.credit_pending, self.credit_pending_where,
                  self.mother_name, self.rating, self.frequency):
            w.setEnabled(self.full)
        return page

    def _refs_page(self, t: dict) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(theme.SP_M)
        if not self.full:
            rl.addWidget(upgrade_box(FULL_MSG, t, self, compact=True))
        self.references = RowsTable("references", t, "Referências",
                                    "Comercial: quem já vendeu a prazo para ele.\nBancária: banco onde ele tem conta.")
        self.people = RowsTable("people", t, "Pessoas de contato", "Com quem falar na empresa: nome, cargo, ramal.")
        for w in (self.references, self.people):
            w.setEnabled(self.full)
            rl.addWidget(w)
        rl.addStretch(1)
        return page

    def _files_page(self, t: dict) -> QWidget:
        page = QWidget()
        fl = QVBoxLayout(page)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(theme.SP_M)
        fl.addWidget(field_label("Foto", t, "Opcional. Aparece no cadastro."))
        row = QHBoxLayout()
        self.photo_view = QLabel(alignment=Qt.AlignCenter, objectName="logoBox")
        self.photo_view.setFixedSize(64, 64)
        col = QVBoxLayout()
        self.photo_pick = button("Escolher foto…", "link", t, "fa6s.image")
        self.photo_clear = button("Remover foto", "link")
        col.addWidget(self.photo_pick, 0, Qt.AlignLeft)
        col.addWidget(self.photo_clear, 0, Qt.AlignLeft)
        col.addStretch(1)
        row.addWidget(self.photo_view)
        row.addLayout(col, 1)
        fl.addLayout(row)
        self.photo_pick.clicked.connect(self._pick_photo)
        self.photo_clear.clicked.connect(lambda: self._set_photo(None))
        self.files = AttachmentsBox(t, for_contact=True)
        self.files.changed.connect(self.sub.setText)
        fl.addWidget(self.files)
        fl.addStretch(1)
        return page

    def _pick_photo(self):
        if not self.full:
            show_upgrade(self, FULL_MSG)
            return
        path, _ = QFileDialog.getOpenFileName(self, "Foto do contato", "", "Imagens (*.png *.jpg *.jpeg *.bmp)")
        if path:
            try:
                self._set_photo(scaled_png(path, 256))
            except ValueError as e:
                self._error(str(e))

    def _set_photo(self, png: bytes | None):
        """Foto escolhida (ou removida): grava na hora, como os anexos."""
        if self.current is None:
            return
        try:
            with Session() as s:
                contacts.set_photo(s, self.current.id, png)
        except ValueError as e:
            self._error(str(e))
            return
        self._show_photo(png)

    def _show_photo(self, png: bytes | None):
        pix = logo_pixmap(png, 64)
        self.photo_view.setPixmap(pix) if pix else self.photo_view.clear()
        self.photo_view.setText("" if pix else "Sem foto")
        self.photo_clear.setVisible(pix is not None)

    def _fill_files(self, c: ContactView | None):
        png = None
        if c is not None and self.full:
            with Session() as s:
                png = contacts.get_photo(s, c.id)
        self._show_photo(png)
        self.photo_pick.setEnabled(c is not None)
        self.files.set_entry(c.id if c else None)

    def _lists_data(self) -> dict | None:
        """None na edição Free: as listas ficam como estão."""
        if not self.full:
            return None
        return {w.key: w.rows() for w in (self.banks, self.references, self.people)}

    def _credit_data(self) -> dict | None:
        """None na edição Free: o crédito fica como está."""
        if not self.full:
            return None
        return {"credit_limit": self.credit_limit.text(), "credit_checked_on": self.credit_checked_on.text(),
                "credit_pending": self.credit_pending.isChecked(),
                "credit_pending_where": self.credit_pending_where.text(), "mother_name": self.mother_name.text(),
                "rating": self.rating.currentData(), "purchase_frequency": self.frequency.currentData()}

    def _fill_credit(self, c: ContactView | None):
        cr = c.credit if c else {}
        limit, checked = cr.get("credit_limit"), cr.get("credit_checked_on")
        self.credit_limit.setText(money.fmt(limit, self.profile.currency) if limit is not None else "")
        self.credit_checked_on.setText(checked.strftime("%d/%m/%Y") if checked else "")
        self.credit_pending.setChecked(bool(cr.get("credit_pending")))
        self.credit_pending_where.setText(cr.get("credit_pending_where") or "")
        self.credit_pending_where.setEnabled(self.full and self.credit_pending.isChecked())
        self.mother_name.setText(cr.get("mother_name") or "")
        self.rating.setCurrentIndex(max(0, self.rating.findData(cr.get("rating"))))
        self.frequency.setCurrentIndex(max(0, self.frequency.findData(cr.get("purchase_frequency"))))

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
        data |= {k: e.text() for k, e in self.date_edits.items()}
        return data

    def _fill_details(self, c: ContactView | None):
        for k, e in self.details.items():
            e.setText(c.get(k) if c else "")
        self.notes.setPlainText(c.get("notes") if c else "")
        for k, e in self.date_edits.items():
            d = c.details.get(k) if c else None
            e.setText(d.strftime("%d/%m/%Y") if d else "")
        self._fill_credit(c)
        lists = {}
        if c is not None and self.full:
            with Session() as s:
                lists = contacts.get_lists(s, c.id)
        for w in (self.banks, self.references, self.people):
            w.set_rows(lists.get(w.key, []))
        self._fill_files(c)
        self.tab_group.button(0).setChecked(True)
        self.pages.setCurrentIndex(0)
        self.shared.setChecked(bool(c and c.shared))

    def _ptype(self) -> str:
        return self.type_group.checkedButton().property("ptype")

    def _type_changed(self):
        pf = self._ptype() == "PF"
        self.doc_lbl.label.setText("CPF" if pf else "CNPJ")
        self.doc2_box.itemAt(0).widget().label.setText("RG" if pf else "Inscrição estadual")
        self.doc.setPlaceholderText("000.000.000-00" if pf else "00.000.000/0000-00")
        self.mother_box.setVisible(pf)
        self.birthday_lbl.label.setText("Aniversário" if pf else "Fundação")
        self.people.setVisible(not pf)

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
        self._split_district()
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
        for key, value in (("address", addr.address), ("district", addr.district), ("city", addr.city),
                           ("state", addr.state)):
            if value:
                self.details[key].setText(value)
        self._split_district()
        self.details["address"].setFocus()
        self.details["address"].end(False)

    def _split_district(self):
        """A busca devolve "Rua X, Bairro": com o bairro no campo próprio, ele sai do fim do endereço."""
        district = self.details["district"].text().strip()
        address = self.details["address"].text().strip()
        if district and address.lower().endswith(", " + district.lower()):
            self.details["address"].setText(address[: -len(district) - 2])

    def _fill_empty(self, details: dict) -> list[str]:
        """Põe os dados nos campos ainda vazios (não apaga o que você já digitou). Devolve o que preencheu."""
        labels = {"phone": "telefone", "email": "e-mail", "zip_code": "CEP", "address": "endereço",
                  "city": "cidade", "state": "UF", "district": "bairro"}
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
        self.merge_btn.hide()
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
        self.merge_btn.show()
        self._error(None)

    def _save(self):
        data = dict(name=self.name.text(), person_type=self._ptype(), document=self.doc.text(),
                    roles={k for k, b in self.role_btns.items() if b.isChecked()}, details=self._details_data(),
                    shared=self.shared.isChecked(), credit=self._credit_data(),
                    lists=self._lists_data())
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

    def _merge(self):
        c = self.current
        if c is None:
            return
        dlg = MergeDialog(self, self.profile.id, c, self.t)
        self.merge_dialog = dlg                  # os testes de tela pegam o diálogo aberto
        if dlg.exec() == QDialog.Accepted and dlg.outcome:
            self.saved.emit(dlg.outcome, c.id)


class MergeDialog(QDialog):
    """Escolher o contato repetido que será juntado ao contato aberto (o aberto fica)."""

    def __init__(self, parent, entity_id: int, keep: ContactView, t: dict):
        super().__init__(parent)
        self.entity_id, self.keep, self.outcome = entity_id, keep, ""
        self.setWindowTitle("Mesclar contatos")
        self.setMinimumWidth(460)
        with Session() as s:
            others = [x for x in contacts.list_contacts(s, entity_id) if x.id != keep.id]
            dup = set(contacts.duplicates(s, entity_id, keep.id))
        self.others = {x.id: x for x in others}
        others.sort(key=lambda x: (x.id not in dup, x.name.lower()))
        lay = QVBoxLayout(self)
        lay.setSpacing(theme.SP_M)
        lay.addWidget(QLabel(f"Juntar a \"{keep.name}\" o contato:", objectName="sectionTitle", wordWrap=True))
        self.pick = QComboBox(editable=True)
        self.pick.setInsertPolicy(QComboBox.NoInsert)
        for x in others:
            self.pick.addItem(f"{x.name}  ·  provável repetido" if x.id in dup else x.name, x.id)
        self.pick.completer().setFilterMode(Qt.MatchContains)
        self.pick.completer().setCompletionMode(QCompleter.PopupCompletion)
        lay.addWidget(self.pick)
        self.info = QLabel(wordWrap=True)
        self.info.setProperty("role", "muted")
        lay.addWidget(self.info)
        self.error = QLabel(wordWrap=True)
        self.error.setProperty("tone", "neg")
        lay.addWidget(self.error)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancelar", "secondary")
        self.ok_btn = button("Mesclar", "primary")
        btns.addWidget(cancel)
        btns.addWidget(self.ok_btn)
        lay.addLayout(btns)
        cancel.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.merge)
        self.pick.currentIndexChanged.connect(self._update)
        self._update()

    def chosen(self) -> ContactView | None:
        return self.others.get(self.pick.currentData())

    def _update(self):
        x = self.chosen()
        self.ok_btn.setEnabled(x is not None)
        self.error.clear()
        self.info.setText("" if x is None else
                          f"Os {x.entries} lançamento(s) de \"{x.name}\" (e regras, estoque e vendas) passam para "
                          f"\"{self.keep.name}\", que ganha os papéis e os dados que faltam. \"{x.name}\" deixa de "
                          "existir. Fica registrado no histórico.")

    def merge(self):
        x = self.chosen()
        if x is None:
            return
        try:
            with Session() as s:
                r = contacts.merge(s, self.keep.id, x.id)
        except ValueError as e:
            self.error.setText(str(e))
            return
        self.outcome = f"\"{x.name}\" foi juntado a \"{self.keep.name}\" ({r.entries} lançamento(s))."
        self.accept()


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
            if k in contacts.ROLES:
                b.setToolTip(contacts.ROLES[k][2])
            elif k == "review":
                b.setToolTip("Contatos criados sozinhos (importação do MCC) para você conferir.\n"
                             "Salvar o contato tira a marca.")
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
            if b.property("role_key") == "review":            # só aparece quando há o que revisar
                b.setVisible(bool(n["review"]) or self.role == "review")

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
