"""Assistente "Trazer dados do MCC" (Fase 2.11): arquivo, prévia que não grava, importar, conferência."""
import shutil
from pathlib import Path

from sqlalchemy import func, select

from finora.core import db
from finora.models import Entity
from finora.services import backup
from finora.services.mcc_import import conference
from finora.ui.mcc_import_dialog import MccImportDialog

DATA = Path(__file__).parents[1] / "data"


def _mcc(tmp_path) -> Path:
    p = tmp_path / "mcc" / "mcc.db"
    p.parent.mkdir()
    shutil.copy2(DATA / "mcc_exemplo.db", p)
    return p


def _entities() -> int:
    with db.Session() as s:
        return s.scalar(select(func.count(Entity.id)))


def test_previa_importar_e_concluir(plus, window, dialogs, tmp_path):
    page = window.page("settings")
    assert page.mcc_btn is not None
    dlg = MccImportDialog(page, page.t)
    got = []
    dlg.imported.connect(lambda: got.append(1))
    assert not dlg.next_btn.isEnabled()                              # sem arquivo
    dialogs.open_path = str(_mcc(tmp_path))
    dlg.pick_btn.click()
    assert len(dlg.checks) == 2 and dlg.next_btn.isEnabled()

    dlg.next_btn.click()                                             # prévia
    assert dlg.stack.currentIndex() == 1 and dlg.report.ok
    assert "Nada foi gravado" in dlg.status.text() and dlg.table.rowCount() > 0
    assert dlg.next_btn.text() == "Importar" and dlg.next_btn.isEnabled()
    assert _entities() == 1 and not got                              # só o perfil: a prévia desfez tudo

    dlg.next_btn.click()                                             # importa de verdade
    assert dlg.done and dlg.next_btn.text() == "Concluir" and "Importado" in dlg.status.text()
    assert _entities() == 3 and got == [1]
    assert dlg.result.backup.name.startswith(backup.IMPORT_PREFIX) and dlg.result.backup.exists()
    assert "Backup de antes" in dlg.counts.text()

    again = MccImportDialog(page, page.t)                            # 2ª vez: avisa que atualiza
    again.load(dialogs.open_path)
    assert all("já importada" in c.text() for c in again.checks.values())


def test_previa_que_nao_bate_nao_deixa_importar(plus, window, dialogs, tmp_path, monkeypatch):
    monkeypatch.setattr(conference.Conference, "ok", property(lambda self: False))
    page = window.page("settings")
    dlg = MccImportDialog(page, page.t)
    dlg.load(str(_mcc(tmp_path)))
    dlg.checks[2].setChecked(False)                                  # só a empresa 1
    dlg.next_btn.click()
    assert "diferenças sem explicação" in dlg.status.text()
    assert not dlg.next_btn.isEnabled() and "não bateu" in dlg.next_btn.toolTip()
    dlg.back_btn.click()
    assert dlg.stack.currentIndex() == 0 and dlg.next_btn.text() == "Ver prévia"


def test_arquivo_que_nao_e_do_mcc(plus, window, tmp_path):
    bad = tmp_path / "outro.db"
    bad.write_bytes(b"isso nao e um banco")
    page = window.page("settings")
    dlg = MccImportDialog(page, page.t)
    dlg.load(str(bad))
    assert dlg.error.text() and not dlg.checks and not dlg.next_btn.isEnabled()


def test_bloqueado_na_free(window):
    assert window.page("settings").mcc_btn is None


PLANILHAS = sorted((DATA / "mcc_planilhas").glob("*.csv"))


def test_planilhas_do_mcc_original(plus, window, dialogs):
    page = window.page("settings")
    dlg = MccImportDialog(page, page.t)
    dlg.load_sheets([str(p) for p in PLANILHAS])
    assert dlg.mode == "sheets" and not dlg.sheets_box.isHidden() and not dlg.checks
    assert "Relatório Analítico (2)" in dlg.file_lbl.text() and "anotacoes.csv" in dlg.info.text()
    assert not dlg.next_btn.isEnabled()                              # falta o nome da empresa
    dlg.company.setText("Sítio Exemplo")
    assert dlg.next_btn.isEnabled()

    dlg.next_btn.click()                                             # prévia: monta o banco e confere
    assert dlg.report.ok and dlg.next_btn.text() == "Importar", dlg.report.problems
    assert "Saldo de Banco Azul: MCC R$ 2.500,00 · montado R$ 2.500,00" in dlg.notes.text()
    assert _entities() == 1

    dlg.next_btn.click()                                             # importa
    assert dlg.done and _entities() == 2
    with db.Session() as s:
        assert s.scalar(select(Entity.name).where(Entity.name == "Sítio Exemplo")) == "Sítio Exemplo"

    again = MccImportDialog(page, page.t)                            # de novo, mesma empresa: atualiza
    again.load_sheets([str(p) for p in PLANILHAS])
    again.company.setText("Sítio Exemplo")
    again.next_btn.click()
    assert "já foi importada das planilhas" in again.notes.text()
    assert again.result.reimport and again.result.created == 0


def test_planilhas_sem_o_analitico(plus, window):
    page = window.page("settings")
    dlg = MccImportDialog(page, page.t)
    dlg.load_sheets([str(DATA / "mcc_planilhas" / "contas.csv")])
    assert "Analítico" in dlg.error.text() and dlg.mode == "db"
