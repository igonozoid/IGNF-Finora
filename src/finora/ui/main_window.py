import sys
from datetime import date

from PySide6.QtCore import QProcess, Qt, QSize
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QButtonGroup,
    QStackedWidget, QScrollArea, QHBoxLayout, QVBoxLayout,
)
import qtawesome as qta

from finora import __version__
from finora.core import settings
from finora.core.db import DATA_DIR
from finora.core.licensing import current_edition
from finora.core.money import CURRENCIES
from finora.services.setup import Profile
from finora.ui import theme
from finora.ui.accounts_page import AccountsPage
from finora.ui.categories_page import CategoriesPage
from finora.ui.contacts_page import ContactsPage
from finora.ui.dashboard_page import DashboardPage
from finora.ui.entries_page import MONTHS, EntriesPage
from finora.ui.header_tools import GlobalSearch, PeriodChip
from finora.ui.pages import PlaceholderPage
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
    ("contacts", "fa6s.address-book", "Contatos", "Pessoas e empresas com quem você troca dinheiro",
     "Aqui você vai cadastrar quem te paga e quem você paga, para encontrar tudo mais rápido."),
    ("reports", "fa6s.file-lines", "Relatórios", "DRE, fluxo de caixa, extratos e atrasados",
     "Aqui você vai ver, mês a mês, quanto entrou, quanto saiu e quanto sobrou."),
    ("settings", "fa6s.gear", "Configurações", "Preferências, backup e licença",
     "Aqui você vai ajustar o app, fazer cópia de segurança dos seus dados e ativar sua licença."),
]

KEYS = [n[0] for n in NAV]
SHOW_NEW_ENTRY = {"dashboard", "entries", "accounts"}
PERIOD_PAGES = {"dashboard", "entries"}       # telas que usam o mês do cabeçalho


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

        brand = QFrame(objectName="brand")
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
        lay.addWidget(self.theme_btn)
        self._lay = lay
        self._dark = False

    def set_profile(self, profile: Profile):
        self._name.setText(profile.name)
        self._name.setToolTip(profile.name)
        self._sub.setText(f"Pessoal · {profile.currency}")
        self._sub.setToolTip(f"Moeda principal: {CURRENCIES[profile.currency][1]}")
        self._brand_icon.setToolTip(f"{profile.name} · Pessoal · {profile.currency}")

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

    def apply_theme(self, name: str, t: dict):
        self._brand_icon.setPixmap(qta.icon("fa6s.coins", color=t["acc"]).pixmap(QSize(16, 16)))
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
        chip = QFrame(objectName="tabChip")
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
        self.theme_btn = QPushButton(objectName="tabTool")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("Alternar entre tema claro e escuro (Ctrl+T)")
        lay.addWidget(self.theme_btn)

    def set_profile(self, profile: Profile):
        self._name.setText(profile.name)
        self._name.setToolTip(f"{profile.name} · Pessoal · {profile.currency}")

    def apply_theme(self, name: str, t: dict):
        self._chip_icon.setPixmap(qta.icon("fa6s.coins", color=t["acc"]).pixmap(QSize(14, 14)))
        for b, icon, _label in self.buttons:
            b.setIcon(qta.icon(icon, color=t["mut"], color_active=t["fg"], color_on=t["fg"]))
        self.theme_btn.setIcon(qta.icon("fa6s.sun" if name == "dark" else "fa6s.moon",
                                        color=t["mut"], color_active=t["fg"]))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Se as abas não cabem com nome, ficam só com ícone (o nome continua na dica).
        full = sum(b.fontMetrics().horizontalAdvance(label) + 40 for b, _i, label in self.buttons) + 240
        compact = self.width() < full
        for b, _icon, label in self.buttons:
            b.setText("" if compact else label)


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
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle, 1)
        lay.addWidget(self.period)
        lay.addWidget(self.search)
        lay.addWidget(self.new_btn)

    def apply_theme(self, t: dict):
        self.new_btn.setIcon(qta.icon("fa6s.plus", color=t["on_acc"]))
        self.search.apply_theme(t)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.subtitle.setVisible(self.width() > 900)     # em janela estreita, sobra espaço para busca e mês
        self.period.set_compact(self.width() < 760)


class MainWindow(QMainWindow):
    def __init__(self, profile: Profile):
        super().__init__()
        self.profile = profile
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
        built = {"dashboard": DashboardPage, "entries": EntriesPage, "accounts": AccountsPage,
                 "categories": CategoriesPage, "contacts": ContactsPage, "reports": ReportsPage,
                 "settings": SettingsPage}
        self.pages = [built[key](profile, t) if key in built else PlaceholderPage(icon, label, text)
                      for key, icon, label, _sub, text in NAV]
        cfg = self.page("settings")
        cfg.theme_requested.connect(self.set_theme)
        cfg.restart_requested.connect(self.restart)
        cfg.nav_requested.connect(self.set_nav)
        cfg.profile_changed.connect(self.set_profile)
        for p in self.pages:
            self.stack.addWidget(p)
            if hasattr(p, "message"):
                p.message.connect(lambda msg: self.statusBar().showMessage(msg, 5000))

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
        self.page("dashboard").open_entry.connect(self.open_entry)
        self.page("dashboard").open_statement.connect(self.open_statement)
        self.page("reports").open_entry.connect(self.open_entry)
        self.header.search.entity_id = profile.id
        self.header.search.chosen.connect(self.open_hit)
        self.header.period.changed.connect(self.set_period)
        self.page("entries").period_changed.connect(self.set_period)
        self.page("entries").period_locked.connect(self.header.period.set_locked)
        self.page("reports").open_statement.connect(self.open_statement)
        self.sidebar.theme_btn.clicked.connect(self.toggle_theme)
        self.header.new_btn.clicked.connect(self.new_entry)
        for i in range(min(len(NAV), 9)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.go_to(i))
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.toggle_theme)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_entry)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.header.search.focus)

        self.theme_name = settings.get_theme(theme.DEFAULT_THEME)
        self.apply_theme(self.theme_name)
        self.apply_nav(settings.get_nav())
        self.go_to("dashboard")

    def page(self, key: str) -> QWidget:
        return self.pages[KEYS.index(key)]

    def current_key(self) -> str:
        return KEYS[self.stack.currentIndex()]

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
        db = QLabel(f"Dados salvos neste computador · {DATA_DIR.name}/finora.db")
        db.setToolTip(str(DATA_DIR / "finora.db"))
        sb.addWidget(db)
        sb.addPermanentWidget(QLabel(f"Edição {current_edition().value.capitalize()}"))
        sb.addPermanentWidget(QLabel(f"v{__version__}"))

    def go_to(self, where: str | int):
        """Abre uma tela pela chave ("entries") ou pela posição no menu."""
        index = KEYS.index(where) if isinstance(where, str) else where
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
        self.header.new_btn.setVisible(key in SHOW_NEW_ENTRY)

    def open_entry(self, entry_id: int):
        self.go_to("entries")
        self.page("entries").open_by_id(entry_id)

    def set_period(self, year: int, month: int):
        """Mês de referência mudou (no cabeçalho ou dentro de Lançamentos): todos acompanham."""
        self.header.period.set(year, month)
        self.page("entries").set_period(year, month)
        self.page("dashboard").set_period(year, month)
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
        self.sidebar.set_profile(profile)
        self.tabs.set_profile(profile)
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
        super().closeEvent(event)
