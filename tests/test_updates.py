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


def test_pacote_do_sistema_e_conferencia():
    data = {"tag_name": "v0.3.0", "assets": [
        {"name": "IGNF-Finora-0.3.0-windows.zip", "browser_download_url": "https://x/w.zip", "digest": "sha256:" + "a" * 64},
        {"name": "IGNF-Finora-0.3.0-linux.tar.gz", "browser_download_url": "https://x/l.tgz"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/sums"}]}
    win = updates.parse_release(data, "win32")
    assert (win.asset_name, win.sha256, win.can_install) == ("IGNF-Finora-0.3.0-windows.zip", "a" * 64, True)
    lin = updates.parse_release(data, "linux")
    assert lin.asset_url == "https://x/l.tgz" and lin.sha256 == "" and lin.sums_url and lin.can_install
    assert not updates.parse_release(data, "darwin").can_install
    sums = f"{'b' * 64}  IGNF-Finora-0.3.0-linux.tar.gz\n{'c' * 64}  outro.zip\n"
    assert updates.sha_from_sums(sums, "IGNF-Finora-0.3.0-linux.tar.gz") == "b" * 64
    assert updates.sha_from_sums(sums, "nada.zip") == ""


def test_pacotes_do_mac(monkeypatch):
    """Mac: um pacote para Apple Silicon e outro para Intel; o aviso acha o certo, mas não instala sozinho (.app)."""
    import platform
    assert updates.platform_suffix("darwin", "arm64") == "-macos-arm64.zip"
    assert updates.platform_suffix("darwin", "x86_64") == "-macos-intel.zip"
    data = {"tag_name": "v0.6.1", "assets": [
        {"name": "IGNF-Finora-0.6.1-macos-arm64.zip", "browser_download_url": "https://x/a.zip", "digest": "sha256:" + "d" * 64},
        {"name": "IGNF-Finora-0.6.1-macos-intel.zip", "browser_download_url": "https://x/i.zip", "digest": "sha256:" + "e" * 64},
        {"name": "IGNF-Finora-0.6.1-windows.zip", "browser_download_url": "https://x/w.zip", "digest": "sha256:" + "f" * 64}]}
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    arm = updates.parse_release(data, "darwin")
    assert (arm.asset_name, arm.can_install) == ("IGNF-Finora-0.6.1-macos-arm64.zip", False)
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert updates.parse_release(data, "darwin").asset_url == "https://x/i.zip"
    assert updates.parse_release(data, "win32").can_install                # Windows continua com um clique
