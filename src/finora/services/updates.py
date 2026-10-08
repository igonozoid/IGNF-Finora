"""Versão nova? O app consulta a última versão publicada no GitHub (Releases) e avisa na barra de status.

A consulta em si é feita pela tela (QNetworkAccessManager, sem travar o app); aqui ficam as regras: endereço,
leitura da resposta e comparação de versões. Nada é enviado além do pedido padrão do navegador.
"""
import re
import sys
from dataclasses import dataclass
from datetime import date

REPO = "igonozoid/IGNF-Finora"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PAGE = f"https://github.com/{REPO}/releases/latest"


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    published: date | None
    notes: str
    asset_name: str = ""          # pacote deste sistema (IGNF-Finora-x.y.z-windows.zip / -linux.tar.gz)
    asset_url: str = ""
    sha256: str = ""              # conferência do download (o GitHub informa em "digest")
    sums_url: str = ""            # SHA256SUMS.txt da versão (se o "digest" não vier)

    @property
    def can_install(self) -> bool:
        return bool(self.asset_url and (self.sha256 or self.sums_url))


def platform_suffix(platform: str | None = None) -> str:
    platform = platform or sys.platform
    return "-windows.zip" if platform == "win32" else "-linux.tar.gz" if platform.startswith("linux") else ""


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2). Partes que não são número (ex.: '-beta') são ignoradas."""
    nums = re.findall(r"\d+", (text or "").split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def parse_release(data: dict, platform: str | None = None) -> Release | None:
    """Resposta da API do GitHub -> Release (None se não for uma versão publicada)."""
    tag = data.get("tag_name") or ""
    if not tag or data.get("draft") or data.get("prerelease"):
        return None
    published = None
    if data.get("published_at"):
        published = date.fromisoformat(data["published_at"][:10])
    suffix = platform_suffix(platform)
    asset = next((a for a in data.get("assets") or [] if suffix and str(a.get("name", "")).endswith(suffix)), None)
    sums = next((a for a in data.get("assets") or [] if a.get("name") == "SHA256SUMS.txt"), None)
    digest = str((asset or {}).get("digest") or "")
    return Release(tag.lstrip("vV"), data.get("html_url") or DOWNLOAD_PAGE, published, (data.get("body") or "")[:2000],
                   (asset or {}).get("name", ""), (asset or {}).get("browser_download_url", ""),
                   digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
                   (sums or {}).get("browser_download_url", ""))


def sha_from_sums(text: str, name: str) -> str:
    """Linha 'abc123…  IGNF-Finora-0.3.0-windows.zip' do SHA256SUMS.txt."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return ""


def due(last_check: str, today: date | None = None) -> bool:
    """Consulta no máximo uma vez por dia."""
    today = today or date.today()
    return last_check != today.isoformat()
