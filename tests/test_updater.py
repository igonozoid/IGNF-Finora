import subprocess
import sys
import zipfile

import pytest

from finora.services import updater

EXE = "IGNF-Finora.exe" if sys.platform == "win32" else "IGNF-Finora"


def _package(tmp_path, version: str):
    pkg = tmp_path / "pacote.zip"
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr(f"IGNF-Finora/{EXE}", f"programa {version}")
        z.writestr("IGNF-Finora/_internal/lib.txt", f"lib {version}")
        z.writestr("IGNF-Finora/LEIA-ME.txt", "leia")
    return pkg


def test_confere_descompacta_e_troca_o_programa_mantendo_os_dados(tmp_path):
    app = tmp_path / "instalado"
    (app / "_internal").mkdir(parents=True)
    (app / EXE).write_text("programa 0.2")
    (app / "_internal" / "lib.txt").write_text("lib 0.2")
    (app / "_internal" / "velho.txt").write_text("sai")
    (app / "data").mkdir()
    (app / "data" / "finora.db").write_text("MEUS DADOS")
    pkg = _package(tmp_path, "0.3")
    with pytest.raises(ValueError, match="não confere"):
        updater.verify(pkg, "0" * 64)
    updater.verify(pkg, updater.sha256(pkg))
    new = updater.extract(pkg, app / updater.UPDATE_DIR / "novo", EXE)
    assert (new / EXE).read_text() == "programa 0.3"
    script = updater.write_script(app, new, 999999, EXE)      # pid que não existe: não espera
    if sys.platform == "win32":
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       capture_output=True, timeout=120)
    else:
        subprocess.run(["/bin/sh", str(script)], capture_output=True, timeout=60)
    assert (app / EXE).read_text() == "programa 0.3"
    assert (app / "_internal" / "lib.txt").read_text() == "lib 0.3" and not (app / "_internal" / "velho.txt").exists()
    assert (app / "data" / "finora.db").read_text() == "MEUS DADOS"                       # dados intactos
    assert (app / updater.UPDATE_DIR / "antigo" / EXE).read_text() == "programa 0.2"      # antigo guardado


def test_pacote_sem_programa_ou_malicioso(tmp_path):
    bad = tmp_path / "x.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../fora.txt", "x")
    with pytest.raises(ValueError):
        updater.extract(bad, tmp_path / "out", EXE)
    empty = tmp_path / "y.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("IGNF-Finora/LEIA-ME.txt", "x")
    with pytest.raises(ValueError, match="não tem o programa"):
        updater.extract(empty, tmp_path / "out2", EXE)
