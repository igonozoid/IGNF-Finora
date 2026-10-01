"""Tokens visuais (cores, fontes, medidas) e geração do QSS.

Nenhum widget usa cor fixa: tudo sai daqui. Para trocar o tema, gere o QSS
de novo com `build_qss(tokens(nome))` e aplique na QApplication.
"""

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


def build_qss(t: dict) -> str:
    return f"""
QMainWindow, QStackedWidget, QWidget#content {{ background: {t['bg']}; }}
QWidget {{ color: {t['fg']}; }}
QToolTip {{ background: {t['panel']}; color: {t['fg']}; border: 1px solid {t['line']}; padding: 4px; }}

/* Barra lateral */
QWidget#sidebar {{ background: {t['panel']}; border-right: 1px solid {t['line']}; }}
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

/* Tela vazia */
QFrame#emptyCard {{ background: {t['panel']}; border: 1px dashed {t['line']}; border-radius: 4px; }}
QLabel#emptyTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#emptyText {{ color: {t['mut']}; }}

/* Barra de status */
QStatusBar {{ background: {t['panel']}; border-top: 1px solid {t['line']}; color: {t['mut']}; font-size: 8pt; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {t['mut']}; padding: 0 {SP_M}px; }}
"""
