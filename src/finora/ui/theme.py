"""Tokens visuais (cores, fontes, medidas) e geração do QSS.

Nenhum widget usa cor fixa: tudo sai daqui. Para trocar o tema, chame
`apply(app, nome)`: aplica a paleta e o QSS gerados dos tokens.
"""
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QFont, QPalette
import qtawesome as qta

LIGHT = dict(bg="#fbfaf8", panel="#f3f2ef", fg="#1d1e20", mut="#6c6e72", line="#e2e0db", acc="#e09a0a", pos="#2f8a4f", neg="#c24a3a",
             on_acc="#1a1200", acc_hover="#c98a08")
DARK  = dict(bg="#16171a", panel="#1d1f23", fg="#e7e6e3", mut="#8d8f94", line="#2c2f34", acc="#f0a91c", pos="#5cb87a", neg="#e2705f",
             on_acc="#1a1200", acc_hover="#f5bb4a")

THEMES = {"light": LIGHT, "dark": DARK}
DEFAULT_THEME = "light"

# Fontes: a primeira disponível no sistema é usada.
FONT_UI = ["IBM Plex Sans", "Segoe UI"]
FONT_MONO = ["IBM Plex Mono", "Consolas"]
FONT_PT = 9

# Densidade
ROW_H = 26
SP_S, SP_M, SP_L = 4, 8, 12


def tokens(name: str) -> dict:
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def mono_font() -> QFont:
    f = QFont()
    f.setFamilies(FONT_MONO)
    f.setPointSize(FONT_PT)
    return f


def build_palette(t: dict) -> QPalette:
    """Paleta para as partes que o Qt desenha sozinho (setas, listas, seleção)."""
    p = QPalette()
    c = lambda k: QColor(t[k])
    for role, key in [
        (QPalette.Window, "bg"), (QPalette.Base, "bg"), (QPalette.AlternateBase, "panel"),
        (QPalette.Button, "panel"), (QPalette.WindowText, "fg"), (QPalette.Text, "fg"),
        (QPalette.ButtonText, "fg"), (QPalette.BrightText, "fg"), (QPalette.PlaceholderText, "mut"),
        (QPalette.ToolTipBase, "panel"), (QPalette.ToolTipText, "fg"),
        (QPalette.Highlight, "acc"), (QPalette.HighlightedText, "on_acc"),
        (QPalette.Mid, "line"), (QPalette.Dark, "line"), (QPalette.Light, "panel"), (QPalette.Link, "acc"),
    ]:
        p.setColor(role, c(key))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c("mut"))
    return p


def _icon_file(name: str, color: str, px: int = 10) -> str:
    """O QSS só aceita imagem por arquivo: renderiza o ícone num PNG temporário."""
    d = Path(tempfile.gettempdir()) / "finora_icons"
    d.mkdir(exist_ok=True)
    f = d / f"{name.replace('.', '_')}_{color.lstrip('#')}_{px}.png"
    if not f.exists():
        qta.icon(name, color=color).pixmap(QSize(px, px)).save(str(f))
    return f.as_posix()


def apply(app, name: str) -> dict:
    t = tokens(name)
    app.setPalette(build_palette(t))
    app.setStyleSheet(build_qss(t, arrow=_icon_file("fa6s.chevron-down", t["mut"]),
                                check=_icon_file("fa6s.check", t["on_acc"])))
    return t


def build_qss(t: dict, arrow: str = "", check: str = "") -> str:
    return f"""
QMainWindow, QStackedWidget, QWidget#content {{ background: {t['bg']}; }}
QWidget {{ color: {t['fg']}; }}
QToolTip {{ background: {t['panel']}; color: {t['fg']}; border: 1px solid {t['line']}; padding: 4px; }}

/* Barra lateral */
QWidget#sidebar {{ background: {t['panel']}; border-right: 1px solid {t['line']}; }}
QScrollArea#navScroll, QWidget#navList {{ background: transparent; }}
QFrame#brand {{ background: {t['bg']}; border: 1px solid {t['line']}; border-radius: 4px; }}
QLabel#brandName {{ font-weight: 600; }}
QLabel#brandSub {{ color: {t['mut']}; font-size: 8pt; }}
QPushButton#navItem {{
    text-align: left; padding: 6px 8px; border: none; border-radius: 4px;
    color: {t['mut']}; background: transparent;
}}
QPushButton#navItem:hover {{ color: {t['fg']}; }}
QPushButton#navItem:checked {{
    color: {t['fg']}; background: {t['bg']}; font-weight: 600;
    border-left: 2px solid {t['acc']}; padding-left: 6px;
    border-top-left-radius: 0; border-bottom-left-radius: 0;
}}
QPushButton#themeToggle {{
    text-align: left; padding: 6px 8px; border: none; border-top: 1px solid {t['line']};
    border-radius: 0; color: {t['mut']}; background: transparent;
}}
QPushButton#themeToggle:hover {{ color: {t['fg']}; }}
QWidget#sidebar[mode="rail"] QPushButton#navItem {{ text-align: center; padding: 8px 0; }}
QWidget#sidebar[mode="rail"] QPushButton#navItem:checked {{ padding-left: 0; }}
QWidget#sidebar[mode="rail"] QPushButton#themeToggle {{ text-align: center; padding: 8px 0; }}

/* Abas no topo */
QFrame#tabBar {{ background: {t['panel']}; border-bottom: 1px solid {t['line']}; }}
QFrame#tabChip {{ border-right: 1px solid {t['line']}; }}
QPushButton#tabItem {{
    border: none; border-radius: 0; padding: 7px 9px; background: transparent; color: {t['mut']};
}}
QPushButton#tabItem:hover {{ color: {t['fg']}; }}
QPushButton#tabItem:checked {{ color: {t['fg']}; font-weight: 600; border-bottom: 2px solid {t['acc']}; }}
QPushButton#tabTool {{ border: none; background: transparent; padding: 7px; }}

/* Cabeçalho da página */
QFrame#header {{ background: {t['bg']}; border-bottom: 1px solid {t['line']}; }}
QLabel#pageTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#pageSubtitle {{ color: {t['mut']}; }}

/* Botões */
QPushButton[variant="primary"] {{
    background: {t['acc']}; color: {t['on_acc']}; border: none; border-radius: 4px;
    padding: 5px 10px; font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {t['acc_hover']}; }}
QPushButton[variant="primary"]:disabled {{ background: {t['line']}; color: {t['mut']}; }}

QPushButton[variant="secondary"] {{
    background: transparent; color: {t['fg']}; border: 1px solid {t['line']}; border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton[variant="secondary"]:hover {{ border-color: {t['mut']}; }}
QPushButton:disabled {{ color: {t['mut']}; }}

/* Formulários */
QLabel[role="field"] {{ color: {t['mut']}; font-size: 8pt; }}
QLabel[role="error"] {{ color: {t['neg']}; }}
QLabel[role="muted"] {{ color: {t['mut']}; }}
QLineEdit, QComboBox, QDateEdit, QSpinBox {{
    background: {t['bg']}; border: 1px solid {t['line']}; border-radius: 3px;
    padding: 3px 8px; min-height: 18px; selection-background-color: {t['acc']}; selection-color: {t['on_acc']};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 10px; height: 10px; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{ border-color: {t['acc']}; }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled {{ color: {t['mut']}; background: {t['panel']}; }}
QDateEdit::drop-down {{ border: none; width: 20px; }}
QDateEdit::down-arrow {{ image: url("{arrow}"); width: 10px; height: 10px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QLineEdit[invalid="true"] {{ border-color: {t['neg']}; }}
QComboBox QAbstractItemView {{
    background: {t['panel']}; border: 1px solid {t['line']}; outline: 0;
    selection-background-color: {t['acc']}; selection-color: {t['on_acc']};
}}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 12px; height: 12px; border: 1px solid {t['mut']}; border-radius: 3px; background: {t['bg']}; }}
QCheckBox::indicator:checked {{ background: {t['acc']}; border-color: {t['acc']}; image: url("{check}"); }}
QCheckBox::indicator:disabled {{ border-color: {t['line']}; }}
QTreeWidget {{ background: {t['bg']}; border: 1px solid {t['line']}; border-radius: 4px; outline: 0; }}
QTreeWidget::item {{ height: {ROW_H}px; }}

/* Cartões, selos e listas */
QScrollArea#pageScroll, QWidget#pageBody {{ background: transparent; }}
QFrame#card {{ background: {t['panel']}; border: 1px solid {t['line']}; border-radius: 4px; }}
QFrame#card[inactive="true"] QLabel {{ color: {t['mut']}; }}
QFrame#card[selected="true"] {{ border: 1px solid {t['acc']}; }}
QLabel#cardTitle, QLabel#sectionTitle {{ font-weight: 600; }}
QLabel[role="badge"] {{ border: 1px solid {t['line']}; border-radius: 3px; padding: 0 5px; color: {t['mut']}; font-size: 8pt; }}
QLabel[role="total"] {{ font-weight: 600; }}
QPushButton[variant="link"] {{ border: none; background: transparent; color: {t['mut']}; padding: 2px 0; font-size: 8pt; }}
QPushButton[variant="link"]:hover {{ color: {t['fg']}; }}
QFrame#lockBox {{ background: {t['bg']}; border: 1px solid {t['acc']}; border-radius: 4px; }}
QHeaderView::section {{
    background: {t['panel']}; color: {t['mut']}; border: none; border-bottom: 1px solid {t['line']};
    padding: 4px {SP_M}px; font-size: 8pt;
}}
QTreeView::item:selected, QTreeView::branch:selected {{ background: {t['line']}; color: {t['fg']}; }}
QTreeView::item:hover {{ background: {t['panel']}; }}

QLabel[tone="pos"] {{ color: {t['pos']}; }}
QLabel[tone="neg"] {{ color: {t['neg']}; }}
QLabel[tone="mut"] {{ color: {t['mut']}; }}
QFrame#listRow, QFrame#row {{ border: none; border-bottom: 1px solid {t['line']}; }}
QFrame#row:hover {{ background: {t['bg']}; }}
QChartView {{ background: transparent; border: none; }}
QProgressBar {{ background: {t['line']}; border: none; border-radius: 2px; }}
QProgressBar::chunk {{ background: {t['acc']}; border-radius: 2px; }}

/* Assistente de primeiro uso */
QDialog#wizard {{ background: {t['bg']}; }}
QFrame#wizardFooter {{ background: {t['panel']}; border-top: 1px solid {t['line']}; }}
QLabel#wizardStep {{ color: {t['mut']}; font-size: 8pt; }}
QLabel#wizardTitle {{ font-size: 12pt; font-weight: 600; }}
QFrame[step="on"] {{ background: {t['acc']}; border-radius: 1px; }}
QFrame[step="off"] {{ background: {t['line']}; border-radius: 1px; }}

/* Filtros (pílulas) e seletor segmentado */
QPushButton[variant="pill"] {{
    border: 1px solid {t['line']}; border-radius: 4px; padding: 4px 10px; background: transparent; color: {t['fg']};
}}
QPushButton[variant="pill"]:hover {{ border-color: {t['mut']}; }}
QPushButton[variant="pill"]:checked {{ background: {t['fg']}; color: {t['bg']}; border-color: {t['fg']}; }}
QPushButton[variant="seg"] {{
    border: 1px solid {t['line']}; border-radius: 0; padding: 4px 2px; background: {t['bg']}; color: {t['fg']};
}}
QPushButton[variant="seg"][pos="first"] {{ border-top-left-radius: 4px; border-bottom-left-radius: 4px; }}
QPushButton[variant="seg"][pos="last"] {{ border-top-right-radius: 4px; border-bottom-right-radius: 4px; }}
QPushButton[variant="seg"]:checked {{ background: {t['fg']}; color: {t['bg']}; border-color: {t['fg']}; }}
QPushButton[variant="danger"] {{ border: none; background: transparent; color: {t['neg']}; padding: 5px 4px; }}
QPushButton[variant="danger"]:hover {{ text-decoration: underline; }}
QPushButton[variant="icon"] {{ border: 1px solid {t['line']}; border-radius: 4px; background: transparent; padding: 4px 6px; }}
QPushButton[variant="icon"]:hover {{ border-color: {t['mut']}; }}
QLabel#monthLabel {{ font-weight: 600; padding: 0 4px; }}

QPushButton[variant="chip"] {{
    border: 1px solid {t['line']}; border-radius: 3px; padding: 2px 8px; background: transparent; color: {t['fg']};
}}
QPushButton[variant="chip"]:hover {{ border-color: {t['mut']}; }}
QPushButton[variant="chip"]:checked {{ background: {t['acc']}; color: {t['on_acc']}; border-color: {t['acc']}; }}
QLabel#avatar {{ background: {t['line']}; border-radius: 14px; font-weight: 600; font-size: 8pt; }}
QListWidget#contactList, QListWidget#statementList {{ background: {t['bg']}; border: 1px solid {t['line']}; border-radius: 4px; outline: 0; }}
QListWidget#contactList::item, QListWidget#statementList::item {{ border-bottom: 1px solid {t['line']}; }}
QListWidget#contactList::item:selected, QListWidget#statementList::item:selected {{ background: {t['panel']}; border-left: 2px solid {t['acc']}; }}
QListWidget#contactList::item:hover:!selected, QListWidget#statementList::item:hover:!selected {{ background: {t['panel']}; }}

/* Tabela */
QTableView {{
    background: {t['bg']}; border: 1px solid {t['line']}; border-radius: 4px; outline: 0;
    selection-background-color: {t['line']}; selection-color: {t['fg']};
}}
QTableView::item {{ border-bottom: 1px solid {t['line']}; padding: 0 4px; }}
QTableView::item:selected {{ background: {t['line']}; color: {t['fg']}; }}
QFrame#totalsBar QLabel {{ color: {t['mut']}; }}
QFrame#totalsBar QLabel[role="total"] {{ color: {t['fg']}; }}
QFrame#totalsBar QLabel[role="accent"] {{ color: {t['acc']}; font-weight: 600; }}

/* Menu de contexto */
QMenu {{ background: {t['panel']}; border: 1px solid {t['line']}; padding: 4px 0; }}
QMenu::item {{ padding: 5px 18px 5px 10px; }}
QMenu::item:selected {{ background: {t['line']}; color: {t['fg']}; }}
QMenu::separator {{ height: 1px; background: {t['line']}; margin: 4px 0; }}

/* Tela vazia */
QFrame#emptyCard {{ background: {t['panel']}; border: 1px dashed {t['line']}; border-radius: 4px; }}
QLabel#emptyTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#emptyText {{ color: {t['mut']}; }}

/* Barra de status */
QStatusBar {{ background: {t['panel']}; border-top: 1px solid {t['line']}; color: {t['mut']}; font-size: 8pt; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {t['mut']}; padding: 0 {SP_M}px; }}
"""
