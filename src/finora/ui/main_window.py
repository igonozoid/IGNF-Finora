from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QButtonGroup,
    QStackedWidget, QHBoxLayout, QVBoxLayout,
)
import qtawesome as qta

from finora import __version__
from finora.core import settings
from finora.core.db import DATA_DIR
from finora.core.licensing import current_edition
from finora.ui import theme
from finora.ui.pages import PlaceholderPage

# (ícone, rótulo, subtítulo do cabeçalho, texto da tela vazia)
NAV = [
    ("fa6s.gauge", "Dashboard", "Visão geral do mês",
     "Aqui você vai ver seu saldo, o que entra e sai nos próximos dias e onde seu dinheiro está indo."),
    ("fa6s.right-left", "Lançamentos", "Contas a pagar e a receber",
     "Aqui você vai registrar receitas, despesas e transferências — inclusive as que se repetem todo mês."),
    ("fa6s.building-columns", "Contas", "Bancos, carteira, cartões e investimentos",
     "Aqui você vai cadastrar onde seu dinheiro fica: conta no banco, dinheiro na carteira, cartão de crédito…"),
    ("fa6s.tags", "Categorias", "Para onde vai cada real",
     "Aqui você vai organizar seus gastos e ganhos em grupos, como Moradia, Alimentação e Lazer."),
    ("fa6s.address-book", "Contatos", "Pessoas e empresas com quem você troca dinheiro",
     "Aqui você vai cadastrar quem te paga e quem você paga, para encontrar tudo mais rápido."),
    ("fa6s.file-lines", "Relatórios", "DRE pessoal e fluxo de caixa",
     "Aqui você vai ver, mês a mês, quanto entrou, quanto saiu e quanto sobrou."),
    ("fa6s.gear", "Configurações", "Preferências, backup e licença",
     "Aqui você vai ajustar o app, fazer cópia de segurança dos seus dados e ativar sua licença."),
]


class Sidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(200)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP_M, 10, theme.SP_M, 0)
        lay.setSpacing(2)

        brand = QFrame(objectName="brand")
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(theme.SP_M, theme.SP_M, theme.SP_M, theme.SP_M)
        bl.setSpacing(theme.SP_M)
        self._brand_icon = QLabel()
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(QLabel("IGNF Finora", objectName="brandName"))
        names.addWidget(QLabel("Finanças pessoais", objectName="brandSub"))
        bl.addWidget(self._brand_icon)
        bl.addLayout(names, 1)
        lay.addWidget(brand)
        lay.addSpacing(10)

        self.group = QButtonGroup(self, exclusive=True)
        self.buttons = []
        for i, (icon, label, *_rest) in enumerate(NAV):
            b = QPushButton(label, objectName="navItem", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(14, 14))
            b.setToolTip(f"{label} (Ctrl+{i + 1})")
            self.group.addButton(b, i)
            self.buttons.append((b, icon))
            lay.addWidget(b)

        lay.addStretch(1)
        self.theme_btn = QPushButton(objectName="themeToggle")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setIconSize(QSize(14, 14))
        lay.addWidget(self.theme_btn)

    def apply_theme(self, name: str, t: dict):
        self._brand_icon.setPixmap(qta.icon("fa6s.coins", color=t["acc"]).pixmap(QSize(16, 16)))
        for b, icon in self.buttons:
            b.setIcon(qta.icon(icon, color=t["mut"], color_active=t["fg"], color_on=t["fg"]))
        dark = name == "dark"
        self.theme_btn.setText("Tema claro" if dark else "Tema escuro")
        self.theme_btn.setIcon(qta.icon("fa6s.sun" if dark else "fa6s.moon", color=t["mut"], color_active=t["fg"]))
        self.theme_btn.setToolTip("Alternar entre tema claro e escuro (Ctrl+T)")


class Header(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(44)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(theme.SP_L)
        self.title = QLabel(objectName="pageTitle")
        self.subtitle = QLabel(objectName="pageSubtitle")
        self.new_btn = QPushButton("Novo lançamento")
        self.new_btn.setProperty("variant", "primary")
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setToolTip("Registrar uma receita, despesa ou transferência (Ctrl+N)")
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)
        lay.addStretch(1)
        lay.addWidget(self.new_btn)

    def apply_theme(self, t: dict):
        self.new_btn.setIcon(qta.icon("fa6s.plus", color=t["on_acc"]))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IGNF Finora — Finanças pessoais")
        self.resize(1366, 800)
        self.setMinimumSize(1024, 640)
        geo = settings.get_geometry()
        if geo is not None:
            self.restoreGeometry(geo)

        self.sidebar = Sidebar()
        self.header = Header()
        self.stack = QStackedWidget()
        self.pages = [PlaceholderPage(icon, label, text) for icon, label, _sub, text in NAV]
        for p in self.pages:
            self.stack.addWidget(p)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.header)
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
        self.sidebar.theme_btn.clicked.connect(self.toggle_theme)
        self.header.new_btn.clicked.connect(lambda: self.go_to(1))
        for i in range(len(NAV)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.go_to(i))
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.toggle_theme)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.go_to(1))

        self.theme_name = settings.get_theme(theme.DEFAULT_THEME)
        self.apply_theme(self.theme_name)
        self.go_to(0)

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.setFixedHeight(24)
        db = QLabel(f"Dados salvos neste computador · {DATA_DIR.name}/finora.db")
        db.setToolTip(str(DATA_DIR / "finora.db"))
        sb.addWidget(db)
        sb.addPermanentWidget(QLabel(f"Edição {current_edition().value.capitalize()}"))
        sb.addPermanentWidget(QLabel(f"v{__version__}"))

    def go_to(self, index: int):
        _icon, label, subtitle, _text = NAV[index]
        self.stack.setCurrentIndex(index)
        self.sidebar.group.button(index).setChecked(True)
        self.header.title.setText(label)
        self.header.subtitle.setText(subtitle)

    def apply_theme(self, name: str):
        self.theme_name = name
        t = theme.tokens(name)
        QApplication.instance().setStyleSheet(theme.build_qss(t))
        self.setWindowIcon(qta.icon("fa6s.coins", color=t["acc"]))
        self.sidebar.apply_theme(name, t)
        self.header.apply_theme(t)
        for p in self.pages:
            p.apply_theme(t)

    def toggle_theme(self):
        name = "light" if self.theme_name == "dark" else "dark"
        self.apply_theme(name)
        settings.set_theme(name)
        self.statusBar().showMessage("Tema claro ativado" if name == "light" else "Tema escuro ativado", 2500)

    def closeEvent(self, event):
        settings.set_geometry(self.saveGeometry())
        super().closeEvent(event)
