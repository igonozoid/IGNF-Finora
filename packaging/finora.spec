# PyInstaller: pacote portátil do IGNF Finora (uma pasta com o programa; os dados ficam em data/ ao lado).
# Gere com:  python tools/build.py   (que também cria o ícone, testa o executável e compacta)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src" / "finora"
ICON = ROOT / "packaging" / ("finora.ico" if sys.platform == "win32" else "finora.png")

datas = [
    (str(SRC / "assets"), "finora/assets"),            # fontes IBM Plex + licença OFL
    (str(SRC / "migrations"), "finora/migrations"),    # o Alembic lê as migrações como arquivos
]
datas += collect_data_files("qtawesome")
hidden = (collect_submodules("alembic.ddl") + collect_submodules("finora")
          + ["sqlalchemy.dialects.sqlite", "sqlalchemy.dialects.mysql.pymysql", "pymysql", "bs4", "openpyxl"])

# Partes do Qt que o Finora não usa (deixam o pacote bem menor)
excludes = ["tkinter", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
            "PySide6.Qt3DAnimation", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
            "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtBluetooth",
            "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
            "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtDesigner", "PySide6.QtHelp",
            "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
            "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtNfc", "PySide6.QtSql", "PySide6.QtTest",
            "PySide6.QtXml", "PySide6.QtHttpServer", "PySide6.QtPdfWidgets"]

a = Analysis([str(ROOT / "packaging" / "launcher.py")], pathex=[str(ROOT / "src")], datas=datas,
             hiddenimports=hidden, excludes=excludes, noarchive=False)
# DLLs grandes que o Finora não usa: OpenGL por software, Qt Quick/QML e o leitor de PDF do Qt
DROP = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6virtualkeyboard")
a.binaries = [b for b in a.binaries
              if not Path(b[0]).name.lower().removeprefix("lib").startswith(DROP)]   # Linux: libQt6Quick.so…
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="IGNF-Finora", console=False,
          icon=str(ICON) if ICON.exists() else None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="IGNF-Finora", upx=False)

if sys.platform == "darwin":
    # Mac: o programa vira IGNF-Finora.app (os dados ficam em ~/IGNF-Finora/data, ver core/paths.py).
    # Sem assinatura da Apple por enquanto: o PyInstaller assina "ad hoc" (o Apple Silicon exige) e o Gatekeeper
    # pede para liberar na 1ª vez (ver LEIA-ME).
    import re
    VERSION = re.search(r'__version__ = "([^"]+)"', (SRC / "__init__.py").read_text(encoding="utf-8")).group(1)
    app = BUNDLE(coll, name="IGNF-Finora.app", icon=str(ICON) if ICON.exists() else None,
                 bundle_identifier="br.com.ignf.finora",
                 info_plist={"CFBundleName": "IGNF Finora", "CFBundleDisplayName": "IGNF Finora",
                             "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                             "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0",
                             "NSHumanReadableCopyright": "IGNF"})
