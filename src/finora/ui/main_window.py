import sys
from datetime import date

from PySide6.QtCore import QProcess, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMenu, QMessageBox, QWidget, QFrame, QLabel, QPushButton, QButtonGroup,
    QStackedWidget, QScrollArea, QHBoxLayout, QVBoxLayout,
)
import qtawesome as qta

from finora import __version__
from finora.core import current as cur_user, settings
from finora.core.db import DATA_DIR
from finora.core.licensing import current_edition
from finora.core.money import CURRENCIES
from finora.core.db import Session
from finora.services import permissions, users
from finora.services.setup import Profile
from finora.services.users import UserView
from finora.ui import theme
from finora.ui.accounts_page import AccountsPage
from finora.ui.admin_page import AdminPage
from finora.ui.categories_page import CategoriesPage
from finora.ui.contacts_page import ContactsPage
from finora.ui.cost_centers_page import CostCentersPage
from finora.ui.dashboard_page import DashboardPage
from finora.ui.entries_page import MONTHS, EntriesPage
from finora.ui.header_tools import GlobalSearch, PeriodChip
from finora.ui.pages import PlaceholderPage
from finora.ui.reconcile_page import ReconcilePage
from finora.ui.reports_page import ReportsPage
from finora.ui.settings_page import SettingsPage
from finora.ui.widgets import retheme

# (chave, ícone, rótulo, subtítulo do cabeçalho, texto da tela vazia). Use as chaves, não a posição.
NAV = [
    ("dashboard", "fa6s.gauge", "Dashboard", "Visão geral do mês",
     "Aqui você vai ver seu saldo, o que entra e sai nos próximos dias e onde seu dinheiro está indo."),
    ("entries", "fa6s.right-left", "Lançamentos", "Contas a pagar e a receber",
     "Aqui você vai registrar receitas, despesas e transferências — inclusive as que se repetem todo mês."),
    ("accounts", "fa6s.building-columns", "Contas", "Bancos, carteira, cartões e investimentos",
     "Aqui você vai cadastrar onde seu dinheiro fica: conta no banco, dinheiro na carteira, cartão de crédito…"),
    ("categories", "fa6s.tags", "Categorias", "Para onde vai cada real",
     "Aqui você vai organizar seus gastos e ganhos em grupos, como Moradia, Alimentação e Lazer."),
    ("cost_centers", "fa6s.diagram-project", "Centros de custo", "Orçado x realizado de cada centro",
     "Aqui você separa os gastos por Casa, Carro, Viagem… e acompanha o orçamento de cada um."),
    ("contacts", "fa6s.address-book", "Contatos", "Pessoas e empresas com quem você troca dinheiro",
     "Aqui você vai cadastrar quem te paga e quem você paga, para encontrar tudo mais rápido."),
    ("reconcile", "fa6s.scale-balanced", "Conciliação", "Extrato do banco x seus lançamentos",
     "Aqui você importa o extrato do banco e confere se tudo foi lançado."),
    ("reports", "fa6s.file-lines", "Relatórios", "DRE, fluxo de caixa, extratos, orçamento e atrasados",
     "Aqui você vai ver, mês a mês, quanto entrou, quanto saiu e quanto sobrou."),
    ("admin", "fa6s.shield-halved", "Administração", "Usuários, entidades, permissões e auditoria",
     "Aqui você cadastra quem usa o app, as entidades e o que cada um pode ver."),
    ("settings", "fa6s.gear", "Configurações", "Preferências, backup e licença",
     "Aqui você vai ajustar o app, fazer cópia de segurança dos seus dados e ativar sua licença."),
]

KEYS = [n[0] for n in NAV]
SHOW_NEW_ENTRY = {"dashboard", "entries", "accounts"}
PERIOD_PAGES = {"dashboard", "entries", "cost_centers"}       # telas que usam o mês do cabeçalho


class _Clickable(QFrame):
    """Quadro que avisa quando é clicado (nome no alto do menu: trocar entidade/usuário)."""
    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class Sidebar(QWidget):
    """Menu à esquerda. Modo 'sidebar' (ícone + nome, 200px) ou 'rail' (só ícones, 52px)."""

    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(200)
        self.mode = "sidebar"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_M, 10, theme.SP_M, 0)
        lay.setSpacing(2)

        brand = self.brand = _Clickable(objectName="brand")
        brand.setCursor(Qt.PointingHandCursor)
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(theme.SP_M, theme.SP_M, theme.SP_M, theme.SP_M)
        bl.setSpacing(theme.SP_M)
        self._brand_icon = QLabel()

        self._names = QWidget()
        names = QVBoxLayout(self._names)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        self._name = QLabel(objectName="brandName")
        self._name.setMinimumWidth(1)  # nome longo é cortado, não alarga o menu
        names.addWidget(self._name)
        self._sub = QLabel(objectName="brandSub")
        names.addWidget(self._sub)
        self.set_profile(profile)
        bl.addWidget(self._brand_icon)
        bl.addWidget(self._names, 1)
        self._brand_layout = bl
        lay.addWidget(brand)
        lay.addSpacing(10)

        # Em janelas baixas o menu rola em vez de cortar itens.
        nav = QWidget(objectName="navList")
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(2)
        scroll = QScrollArea(objectName="navScroll", widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(nav)

        self.group = QButtonGroup(self, exclusive=True)
        self.buttons = []
        for i, (_key, icon, label, *_rest) in enumerate(NAV):
            b = QPushButton(label, objectName="navItem", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(14, 14))
            b.setToolTip(f"{label} (Ctrl+{i + 1})")
            self.group.addButton(b, i)
            self.buttons.append((b, icon, label))
            nl.addWidget(b)
        nl.addStretch(1)
        lay.addWidget(scroll, 1)

        self.theme_btn = QPushButton(objectName="themeToggle")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setIconSize(QSize(14, 14))
        self.collapse_btn = QPushButton(objectName="themeToggle")
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.setIconSize(QSize(14, 14))
        self._bottom = QHBoxLayout()
        self._bottom.setContentsMargins(0, 0, 0, 0)
        self._bottom.setSpacing(0)
        self._bottom.addWidget(self.theme_btn, 1)
        self._bottom.addWidget(self.collapse_btn)
        lay.addLayout(self._bottom)
        self._lay = lay
        self._dark = False

    def set_profile(self, profile: Profile, user_name: str = ""):
        self._name.setText(profile.name)
        self._name.setToolTip(f"{profile.name} — clique para trocar de entidade ou de usuário")
        self._sub.setText(f"{user_name or 'Pessoal'} · {profile.currency}")
        self._sub.setToolTip(f"Moeda principal: {CURRENCIES[profile.currency][1]}")
        self._brand_icon.setToolTip(f"{profile.name} · {user_name or 'Pessoal'} · {profile.currency}")

    def set_mode(self, mode: str):
        self.mode = mode
        rail = mode == "rail"
        self.setProperty("mode", mode)
        self.setFixedWidth(52 if rail else 200)
        self._lay.setContentsMargins(*((6, 10, 6, 0) if rail else (theme.SP_M, 10, theme.SP_M, 0)))
        self._names.setVisible(not rail)
        self._brand_layout.setContentsMargins(*((0, 6, 0, 6) if rail else (theme.SP_M,) * 4))
        self._brand_layout.setAlignment(self._brand_icon, Qt.AlignCenter if rail else Qt.AlignLeft)
        for b, _icon, label in self.buttons:
            b.setText("" if rail else label)
        self._theme_text()
        for w in [self] + self.findChildren(QPushButton):
            w.style().unpolish(w)
            w.style().polish(w)

    def _theme_text(self):
        self.theme_btn.setText("" if self.mode == "rail" else ("Tema claro" if self._dark else "Tema escuro"))
        rail = self.mode == "rail"
        self.collapse_btn.setToolTip("Mostrar o menu com nomes" if rail else "Recolher o menu (só ícones)")
        self._bottom.setDirection(QHBoxLayout.TopToBottom if rail else QHBoxLayout.LeftToRight)
        if hasattr(self, "_t"):
            self.collapse_btn.setIcon(qta.icon("fa6s.angles-right" if rail else "fa6s.angles-left",
                                               color=self._t["mut"], color_active=self._t["fg"]))

    def apply_theme(self, name: str, t: dict):
        self._t = t
        self._brand_icon.setPixmap(getattr(self, "logo", None) or
                                   qta.icon("fa6s.coins", color=t["acc"]).pixmap(QSize(16, 16)))
        for b, icon, _label in self.buttons:
            b.setIcon(qta.icon(icon, color=t["mut"], color_active=t["fg"], color_on=t["fg"]))
        dark = self._dark = name == "dark"
        self._theme_text()
        self.theme_btn.setIcon(qta.icon("fa6s.sun" if dark else "fa6s.moon", color=t["mut"], color_active=t["fg"]))
        self.theme_btn.setToolTip("Alternar entre tema claro e escuro (Ctrl+T)")


class TopTabs(QFrame):
    """Menu em abas abaixo do cabeçalho (modo 'tabs' do mockup)."""

    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.setObjectName("tabBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(0)
        chip = self.chip = _Clickable(objectName="tabChip")
        chip.setCursor(Qt.PointingHandCursor)
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(2, 0, 10, 0)
        cl.setSpacing(6)
        self._chip_icon = QLabel()
        self._name = QLabel(objectName="brandName")
        cl.addWidget(self._chip_icon)
        cl.addWidget(self._name)
        self.set_profile(profile)
        lay.addWidget(chip)
        lay.addSpacing(4)
        self.group = QButtonGroup(self, exclusive=True)
        self.buttons = []
        for i, (_key, icon, label, *_rest) in enumerate(NAV):
            b = QPushButton(label, objectName="tabItem", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(11, 11))
            b.setToolTip(f"{label} (Ctrl+{i + 1})")
            self.group.addButton(b, i)
            self.buttons.append((b, icon, label))
            lay.addWidget(b)
        lay.addStretch(1)
        self.icons_btn = QPushButton(objectName="tabTool")
        self.icons_btn.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.icons_btn)
        self.theme_btn = QPushButton(objectName="tabTool")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("Alternar entre tema claro e escuro (Ctrl+T)")
        lay.addWidget(self.theme_btn)
        self.icons_only = settings.get_tabs_icons()
        self.icons_btn.clicked.connect(lambda: self.set_icons_only(not self.icons_only, save=True))

    def set_profile(self, profile: Profile, user_name: str = ""):
        self._name.setText(profile.name)
        self._name.setToolTip(f"{profile.name} · {user_name or 'Pessoal'} · {profile.currency} — clique para trocar")

    def apply_theme(self, name: str, t: dict):
        self._chip_icon.setPixmap(getattr(self, "logo", None) or
                                  qta.icon("fa6s.coins", color=t["acc"]).pixmap(QSize(14, 14)))
        for b, icon, _label in self.buttons:
            b.setIcon(qta.icon(icon, color=t["mut"], color_active=t["fg"], color_on=t["fg"]))
        self.theme_btn.setIcon(qta.icon("fa6s.sun" if name == "dark" else "fa6s.moon",
                                        color=t["mut"], color_active=t["fg"]))
        self._t = t
        self._icons_icon()

    def _icons_icon(self):
        if hasattr(self, "_t"):
            self.icons_btn.setIcon(qta.icon("fa6s.angles-right" if self.icons_only else "fa6s.angles-left",
                                            color=self._t["mut"], color_active=self._t["fg"]))
        self.icons_btn.setToolTip("Mostrar os nomes das abas" if self.icons_only else "Abas só com ícones")

    def set_icons_only(self, on: bool, save: bool = False):
        self.icons_only = on
        if save:
            settings.set_tabs_icons(on)
        self._icons_icon()
        self._fit()

    def _fit(self):
        # Só ícones quando o usuário pediu ou quando as abas não cabem com nome (o nome continua na dica).
        full = sum(b.fontMetrics().horizontalAdvance(label) + 40 for b, _i, label in self.buttons) + 260
        compact = self.icons_only or self.width() < full
        for b, _icon, label in self.buttons:
            b.setText("" if compact else label)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class Header(QFrame):
    def __init__(self, t: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(44)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(theme.SP_L)
        self.title = QLabel(objectName="pageTitle")
        self.subtitle = QLabel(objectName="pageSubtitle")
        self.subtitle.setMinimumWidth(1)
        self.period = PeriodChip(t)
        self.search = GlobalSearch(t)
        self.new_btn = QPushButton("Novo lançamento")
        self.new_btn.setProperty("variant", "primary")
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setToolTip("Registrar uma receita, despesa ou transferência (Ctrl+N)")
        self.help_btn = QPushButton()
        self.help_btn.setProperty("variant", "secondary")
        self.help_btn.setCursor(Qt.PointingHandCursor)
        self.help_btn.setToolTip("Ajuda (F1), atalhos e relatório de problema")
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle, 1)
        lay.addWidget(self.period)
        lay.addWidget(self.search)
        lay.addWidget(self.help_btn)
        lay.addWidget(self.new_btn)

    def apply_theme(self, t: dict):
        self.new_btn.setIcon(qta.icon("fa6s.plus", color=t["on_acc"]))
        self.help_btn.setIcon(qta.icon("fa6s.circle-question", color=t["fg"]))
        self.search.apply_theme(t)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.subtitle.setVisible(self.width() > 900)     # em janela estreita, sobra espaço para busca e mês
        self.period.set_compact(self.width() < 760)


class MainWindow(QMainWindow):
    def __init__(self, profile: Profile, user: UserView | None = None):
        super().__init__()
        self.profile, self.user = profile, user
        self.next_action: str | None = None     # reservado: hoje a troca de entidade/usuário é na mesma janela
        self.quitting = False                   # "Sair" do ícone ao lado do relógio: fecha de verdade
        self.setWindowTitle("IGNF Finora — Finanças pessoais")
        self.setMinimumSize(800, 480)
        geo = settings.get_geometry()
        if geo is None or not self.restoreGeometry(geo):
            self._fit_to_screen()

        self.sidebar = Sidebar(profile)
        self.header = Header(theme.tokens(settings.get_theme(theme.DEFAULT_THEME)))
        self.tabs = TopTabs(profile)
        self.stack = QStackedWidget()
        t = theme.tokens(settings.get_theme(theme.DEFAULT_THEME))
        self.pages = []
        self._build_pages(profile, t)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.header)
        rl.addWidget(self.tabs)
        rl.addWidget(self.stack, 1)

        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.sidebar)
        cl.addWidget(right, 1)
        self.setCentralWidget(central)

        self._build_statusbar()

        self.sidebar.group.idClicked.connect(self.go_to)
        self.tabs.group.idClicked.connect(self.go_to)
        self.tabs.theme_btn.clicked.connect(self.toggle_theme)
        self.header.search.chosen.connect(self.open_hit)
        self.header.period.changed.connect(self.set_period)
        self.sidebar.theme_btn.clicked.connect(self.toggle_theme)
        self.sidebar.collapse_btn.clicked.connect(
            lambda: self.set_nav("sidebar" if self.nav_mode == "rail" else "rail"))
        self.sidebar.brand.clicked.connect(lambda: self._session_menu(self.sidebar.brand))
        self.tabs.chip.clicked.connect(lambda: self._session_menu(self.tabs.chip))
        self.header.new_btn.clicked.connect(self.new_entry)
        for i in range(min(len(NAV), 9)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.go_to(i))
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.toggle_theme)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_entry)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.header.search.focus)
        QShortcut(QKeySequence(Qt.Key_F1), self, activated=lambda: self.show_help())
        help_menu = QMenu(self.header.help_btn)
        help_menu.addAction("Ajuda desta tela (F1)", lambda: self.show_help())
        help_menu.addAction("Atalhos de teclado", lambda: self.show_help("atalhos"))
        help_menu.addAction("Primeiros passos", lambda: self.show_help("inicio"))
        help_menu.addSeparator()
        help_menu.addAction("Enviar relatório de problema…", self.report_problem)
        help_menu.addAction("Sobre o IGNF Finora", self.show_about)
        self.header.help_btn.setMenu(help_menu)

        self.theme_name = settings.get_theme(theme.DEFAULT_THEME)
        self.apply_theme(self.theme_name)
        self.apply_nav(settings.get_nav())
        self._apply_access()
        self.go_to(self.visible_keys[0])
        from finora.ui.tray import Tray
        self.tray = Tray(self)
        QTimer.singleShot(2500, self.tray.check)       # avisa os vencimentos logo depois de abrir

    def _build_pages(self, profile: Profile, t: dict):
        """Monta as telas da entidade aberta (de novo ao trocar de entidade ou de usuário)."""
        built = {"dashboard": DashboardPage, "entries": EntriesPage, "accounts": AccountsPage,
                 "categories": CategoriesPage, "cost_centers": CostCentersPage, "contacts": ContactsPage,
                 "reconcile": ReconcilePage, "reports": ReportsPage, "admin": AdminPage, "settings": SettingsPage}
        for old in self.pages:
            self.stack.removeWidget(old)
            old.deleteLater()
        self.pages = [built[key](profile, t) if key in built else PlaceholderPage(icon, label, text)
                      for key, icon, label, _sub, text in NAV]
        cfg = self.page("settings")
        cfg.theme_requested.connect(self.set_theme)
        cfg.restart_requested.connect(self.restart)
        cfg.nav_requested.connect(self.set_nav)
        cfg.profile_changed.connect(self.set_profile)
        self.page("admin").entities_changed.connect(self._apply_access)     # "Trocar entidade" passa a valer
        for p in self.pages:
            self.stack.addWidget(p)
            if hasattr(p, "message"):
                p.message.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        self.page("dashboard").open_entry.connect(self.open_entry)
        self.page("dashboard").open_statement.connect(self.open_statement)
        self.page("reports").open_entry.connect(self.open_entry)
        self.page("reconcile").open_entry.connect(self.open_entry)
        self.page("entries").import_requested.connect(self.import_ofx)
        self.page("entries").period_changed.connect(self.set_period)
        self.page("entries").period_locked.connect(self.header.period.set_locked)
        self.page("reports").open_statement.connect(self.open_statement)
        self.header.search.entity_id = profile.id

    def reload(self, profile: Profile, user: UserView | None):
        """Troca de entidade/usuário sem fechar a janela: remonta as telas com os dados novos."""
        self.profile, self.user = profile, user
        self._build_pages(profile, theme.tokens(self.theme_name))
        self.apply_theme(self.theme_name)
        self.apply_nav(self.nav_mode)
        self._apply_access()
        self.go_to(self.visible_keys[0])
        who = f" como {user.name}" if user else ""
        self.statusBar().showMessage(f"Aberto: {profile.name}{who}", 5000)
        QTimer.singleShot(1500, self.tray.check)       # vencimentos da entidade que abriu

    # ---------- usuário, entidade e permissões ----------
    def _apply_access(self):
        """Esconde o que o usuário não pode ver e trava a gravação onde ele só pode ler."""
        uid = self.user.id if self.user else None
        with Session() as s:
            lv = permissions.levels(s, uid, self.profile.id)
            self._can_switch_user = users.needs_login(s)
            self._entity_count = len(permissions.entities_for(s, None if not uid or self.user.is_admin else uid))
        self.levels = lv
        cur_user.set_entity(self.profile.id, {m for m, level in lv.items() if level != "full"})
        self.visible_keys = []
        for i, (key, *_r) in enumerate(NAV):
            module = permissions.PAGE_MODULE.get(key)
            if key == "admin":
                visible = lv["admin"] != "none" or lv["audit"] != "none"
            else:
                visible = module is None or lv[module] != "none"
            self.sidebar.buttons[i][0].setVisible(visible)
            self.tabs.buttons[i][0].setVisible(visible)
            if visible:
                self.visible_keys.append(key)
        self.page("admin").set_access(lv["admin"], lv["audit"])
        self.page("settings").set_admin(lv["admin"] == "full")
        name = self.user.name if self.user else ""
        self.sidebar.set_profile(self.profile, name)
        self.tabs.set_profile(self.profile, name)
        self._show_logo()

    def _show_logo(self):
        """Logotipo da entidade no alto do menu (sem logotipo: as moedas do Finora)."""
        from finora.services import entity_admin
        from finora.ui.admin_page import logo_pixmap
        with Session() as s:
            png = entity_admin.get_logo(s, self.profile.id)
        self.sidebar.logo = logo_pixmap(png, 16)
        self.tabs.logo = logo_pixmap(png, 14)
        if self.sidebar.logo is not None:
            self.sidebar._brand_icon.setPixmap(self.sidebar.logo)
            self.tabs._chip_icon.setPixmap(self.tabs.logo)

    def _session_menu(self, anchor: QWidget):
        menu = QMenu(self)
        who = menu.addAction(f"{self.user.name if self.user else self.profile.name} · {self.profile.name}")
        who.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Trocar entidade…", self._switch_entity)
        if self.levels.get("admin") == "full":
            menu.addAction("Nova entidade…", self._new_entity)
        usr = menu.addAction("Trocar de usuário…", lambda: self.switch("user"))
        usr.setVisible(self._can_switch_user)
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _switch_entity(self):
        if self._entity_count > 1:
            self.switch("entity")
            return
        from finora.services import entity_admin
        lim = entity_admin.limit()
        if lim == 1:
            text = ("Você tem uma entidade só. Na edição Free é uma entidade por instalação; nas edições Plus e Pro "
                    "você separa pessoa física, empresa, MEI… e troca entre elas por aqui.")
        else:
            text = ("Você tem uma entidade só. Crie outra em Administração › Entidades e depois troque por aqui.")
        QMessageBox.information(self, "Trocar entidade", text)

    def _new_entity(self):
        self.go_to("admin")
        admin = self.page("admin")
        admin.tab_buttons["entities"].click()
        admin.tabs["entities"]._new()

    def switch(self, action: str):
        """Trocar entidade ou usuário: pergunta (lista de entidades / login) e remonta esta mesma janela."""
        from finora.core import current
        from finora.ui.session_flow import pick_entity, pick_user
        t = theme.tokens(self.theme_name)
        user = self.user
        if action == "user":
            previous = (current.current.user_id, current.current.user_name, current.current.is_admin)
            user = pick_user(t)
            if user is None:                          # desistiu do login: continua como estava
                current.set_user(*previous)
                return
        profile = pick_entity(user, t, ask=action == "entity")
        if profile is None:
            if action == "user":
                QMessageBox.warning(self, "IGNF Finora", "Esse usuário não tem nenhuma entidade liberada.")
            return
        self.reload(profile, user)

    def page(self, key: str) -> QWidget:
        return self.pages[KEYS.index(key)]

    def current_key(self) -> str:
        return KEYS[self.stack.currentIndex()]

    def show_help(self, key: str | None = None):
        """Ajuda (F1): abre na seção da tela atual."""
        from finora.ui.help import HelpDialog
        dlg = HelpDialog(self, theme.tokens(self.theme_name), key or self.current_key())
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()
        self._help = dlg
        return dlg

    def show_about(self):
        self.go_to("settings")
        cfg = self.page("settings")
        cfg.reveal(cfg.about)

    def report_problem(self):
        from finora.ui.help import ProblemDialog
        ProblemDialog(self, theme.tokens(self.theme_name)).exec()

    def _fit_to_screen(self):
        """Tamanho do mockup (1366x800), limitado à área livre da tela, centralizado."""
        area = self.screen().availableGeometry()
        w = min(1366, area.width() - 2 * theme.SP_L)
        h = min(800, area.height() - 2 * theme.SP_L)
        self.resize(w, h)
        self.move(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2)
        if area.height() < 700:
            self.setWindowState(Qt.WindowMaximized)

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.setFixedHeight(24)
        from finora.core import db as dbmod
        where = QLabel(dbmod.describe())
        where.setToolTip(str(DATA_DIR / "finora.db") if not dbmod.is_server() else
                         "Os dados ficam no Finora Servidor; este computador só mostra e grava lá.")
        if dbmod.is_server():
            where.setProperty("tone", "pos")
        sb.addWidget(where)
        sb.addPermanentWidget(QLabel(f"Edição {current_edition().value.capitalize()}"))
        sb.addPermanentWidget(QLabel(f"v{__version__}"))

    def show_update(self, release):
        """Versão nova publicada: link na barra de status (abre a página de download)."""
        link = QLabel(f'<a href="#">Versão {release.version} disponível — atualizar</a>')
        link.linkActivated.connect(lambda _h: self.open_update(release))
        link.setToolTip("Ver as novidades e atualizar (seus dados ficam como estão)")
        self.statusBar().insertPermanentWidget(0, link)
        self.update_link = link

    def open_update(self, release):
        from finora.ui.update_dialog import UpdateDialog
        UpdateDialog(self, release, theme.tokens(self.theme_name)).exec()

    def go_to(self, where: str | int):
        """Abre uma tela pela chave ("entries") ou pela posição no menu."""
        index = KEYS.index(where) if isinstance(where, str) else where
        if NAV[index][0] not in getattr(self, "visible_keys", KEYS):
            return                                   # sem permissão para essa tela (ex.: atalho Ctrl+N)
        key, _icon, label, subtitle, _text = NAV[index]
        page = self.pages[index]
        if hasattr(page, "refresh"):
            page.refresh()
        self.stack.setCurrentIndex(index)
        self.sidebar.group.button(index).setChecked(True)
        self.tabs.group.button(index).setChecked(True)
        self.header.title.setText(label)
        if key == "dashboard":
            y, m = self.header.period.year, self.header.period.month
            subtitle = f"Visão geral de {MONTHS[m - 1]}" + ("" if y == date.today().year else f" de {y}")
        self.header.subtitle.setText(subtitle)
        self.header.period.setVisible(key in PERIOD_PAGES)
        if key != "entries":
            self.header.period.set_locked(False)
        # O botão só aparece onde lançar faz parte do fluxo; o Ctrl+N vale em todas as telas.
        self.header.new_btn.setVisible(key in SHOW_NEW_ENTRY and getattr(self, "levels", {}).get(
            "financial", "full") == "full")

    def open_entry(self, entry_id: int):
        self.go_to("entries")
        self.page("entries").open_by_id(entry_id)

    def set_period(self, year: int, month: int):
        """Mês de referência mudou (no cabeçalho ou dentro de Lançamentos): todos acompanham."""
        self.header.period.set(year, month)
        self.page("entries").set_period(year, month)
        self.page("dashboard").set_period(year, month)
        self.page("cost_centers").set_period(year, month)
        if self.current_key() == "dashboard":
            self.go_to("dashboard")

    def open_hit(self, hit):
        """Resultado escolhido na busca global."""
        if hit.kind == "entry":
            self.open_entry(hit.id)
        elif hit.kind == "contact":
            self.go_to("contacts")
            self.page("contacts").select_contact(hit.id)
        elif hit.kind == "account":
            self.go_to("accounts")
            self.page("accounts")._edit(hit.id)
        elif hit.kind == "category":
            self.go_to("categories")
            self.page("categories").refresh(select_id=hit.id)

    def open_statement(self, account_id: int, due):
        """Fatura de cartão clicada no Dashboard: abre a janela de faturas e atualiza a tela atual."""
        self.page("entries").open_statement(account_id, due)
        self.go_to(self.stack.currentIndex())

    def import_ofx(self):
        """Botão "Importar extrato" de Lançamentos: leva para a Conciliação e já pede o arquivo."""
        self.go_to("reconcile")
        self.page("reconcile")._import()

    def new_entry(self):
        self.go_to("entries")
        self.page("entries").new_entry()

    def apply_theme(self, name: str):
        self.theme_name = name
        t = theme.apply(QApplication.instance(), name)
        self.setWindowIcon(qta.icon("fa6s.coins", color=t["acc"]))
        self.sidebar.apply_theme(name, t)
        self.tabs.apply_theme(name, t)
        self.header.apply_theme(t)
        for p in self.pages:
            p.apply_theme(t)
        retheme(self, t)
        self.page("settings").set_theme_name(name)

    def set_profile(self, profile: Profile):
        """Nome ou moeda mudaram em Configurações: atualiza tudo sem reabrir o app."""
        self.profile = profile
        name = self.user.name if self.user else ""
        self.sidebar.set_profile(profile, name)
        self.tabs.set_profile(profile, name)
        for page in self.pages:
            parts = [page] + [getattr(page, n) for n in ("form", "model", "chart") if hasattr(page, n)]
            for view in getattr(page, "views", {}).values():
                parts += [view] + [getattr(view, n) for n in ("model", "chart") if hasattr(view, n)]
            for obj in parts:
                if hasattr(obj, "profile"):
                    obj.profile = profile
                if isinstance(getattr(obj, "currency", None), str):
                    obj.currency = profile.currency
        if self.page("accounts").editing is None:
            self.page("accounts")._new()                  # "Nova conta" já vem com a moeda nova
        self.go_to(self.stack.currentIndex())     # redesenha a tela atual com os dados novos

    def apply_nav(self, mode: str):
        """Barra lateral, só ícones (trilho) ou abas no topo — as 3 opções do mockup."""
        self.nav_mode = mode
        self.sidebar.setVisible(mode != "tabs")
        self.sidebar.set_mode("rail" if mode == "rail" else "sidebar")
        self.tabs.setVisible(mode == "tabs")
        self.page("settings").set_nav_name(mode)

    def set_nav(self, mode: str):
        self.apply_nav(mode)
        settings.set_nav(mode)
        self.statusBar().showMessage(f"Menu: {settings.NAV_MODES[mode]}", 2500)

    def toggle_theme(self):
        self.set_theme("light" if self.theme_name == "dark" else "dark")

    def set_theme(self, name: str):
        self.apply_theme(name)
        settings.set_theme(name)
        self.statusBar().showMessage("Tema claro ativado" if name == "light" else "Tema escuro ativado", 2500)

    def restart(self):
        """Reabre o app (usado depois de restaurar um backup)."""
        if getattr(sys, "frozen", False):          # executável do instalador
            QProcess.startDetached(sys.executable, sys.argv[1:])
        else:
            QProcess.startDetached(sys.executable, ["-m", "finora"])
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event):
        settings.set_geometry(self.saveGeometry())
        tray = getattr(self, "tray", None)
        if settings.get_tray() and tray is not None and tray.available and not self.quitting and not self.next_action:
            event.ignore()                      # continua ao lado do relógio, avisando os vencimentos
            self.hide()
            if not getattr(self, "_told_tray", False):
                self._told_tray = True
                tray.notify("O Finora continua aberto aqui ao lado do relógio, para avisar os vencimentos. "
                            "Para fechar de vez: botão direito no ícone › Sair.")
            return
        if tray is not None and tray.icon is not None:
            tray.icon.hide()
        super().closeEvent(event)
