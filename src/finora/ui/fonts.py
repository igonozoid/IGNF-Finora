"""Fontes do mockup embutidas no app (IBM Plex Sans e Mono, licença SIL OFL 1.1 em assets/fonts).

Sem isso, no Windows sem as fontes instaladas, o app cairia para Segoe UI/Consolas.
"""
from pathlib import Path

from PySide6.QtGui import QFontDatabase

FONTS_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"


def load() -> set[str]:
    """Registra as fontes no Qt. Retorna as famílias carregadas (ex.: {"IBM Plex Sans", "IBM Plex Mono"})."""
    families: set[str] = set()
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families.update(QFontDatabase.applicationFontFamilies(font_id))
    return families
