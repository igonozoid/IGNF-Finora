"""Português do Brasil nas partes que o próprio Qt desenha: botões padrão ("Sim", "Não", "Cancelar",
"Mostrar detalhes…"), menus de contexto de campos de texto e calendário dos campos de data."""
from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator


def install(app) -> bool:
    loc = QLocale(QLocale.Portuguese, QLocale.Brazil)
    QLocale.setDefault(loc)
    tr = QTranslator(app)
    ok = tr.load(loc, "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath))
    if ok:
        app.installTranslator(tr)
        app._qt_translator = tr    # mantém a referência viva enquanto o app existir
    return ok
