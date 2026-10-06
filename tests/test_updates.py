from datetime import date

from finora.services import updates


def test_compara_versoes():
    assert updates.parse_version("v0.10.2") == (0, 10, 2)
    assert updates.is_newer("0.10.0", "0.9.9") and not updates.is_newer("v0.1.0", "0.1.0")
    assert updates.is_newer("1.0.0-beta", "0.9.0") and updates.parse_version("") == (0,)


def test_le_resposta_do_github():
    rel = updates.parse_release({"tag_name": "v0.2.0", "html_url": "https://github.com/x/releases/tag/v0.2.0",
                                 "published_at": "2026-10-20T12:00:00Z", "body": "Novidades"})
    assert (rel.version, rel.published, rel.notes) == ("0.2.0", date(2026, 10, 20), "Novidades")
    assert updates.parse_release({"tag_name": "v0.3.0", "prerelease": True}) is None
    assert updates.parse_release({}) is None


def test_consulta_uma_vez_por_dia():
    assert updates.due("", date(2026, 10, 6))
    assert not updates.due("2026-10-06", date(2026, 10, 6)) and updates.due("2026-10-05", date(2026, 10, 6))
