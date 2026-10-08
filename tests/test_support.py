import zipfile

from finora.services import support


def test_relatorio_de_problema_sem_segredos(tmp_path):
    log = tmp_path / "finora.log"
    log.write_text("2026-10-08 INFO abriu\nchave FNR1-AEBAH-4XYZ-ABCDEFGHIJ usada\nERRO senha=123\n", encoding="utf-8")
    path = support.build(tmp_path / "out", log, "Travou ao salvar", {"Edição": "pro"})
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        text = z.read("finora.log").decode()
        info = z.read("sistema.txt").decode()
    assert names == {"sistema.txt", "o-que-aconteceu.txt", "finora.log"}
    assert "abriu" in text and "FNR1" not in text and "123" not in text
    assert "IGNF Finora" in info and "Edição: pro" in info
