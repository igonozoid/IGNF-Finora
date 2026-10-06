"""Versão nova? O app consulta a última versão publicada no GitHub (Releases) e avisa na barra de status.

A consulta em si é feita pela tela (QNetworkAccessManager, sem travar o app); aqui ficam as regras: endereço,
leitura da resposta e comparação de versões. Nada é enviado além do pedido padrão do navegador.
"""
import re
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


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2). Partes que não são número (ex.: '-beta') são ignoradas."""
    nums = re.findall(r"\d+", (text or "").split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def parse_release(data: dict) -> Release | None:
    """Resposta da API do GitHub -> Release (None se não for uma versão publicada)."""
    tag = data.get("tag_name") or ""
    if not tag or data.get("draft") or data.get("prerelease"):
        return None
    published = None
    if data.get("published_at"):
        published = date.fromisoformat(data["published_at"][:10])
    return Release(tag.lstrip("vV"), data.get("html_url") or DOWNLOAD_PAGE, published, (data.get("body") or "")[:2000])


def due(last_check: str, today: date | None = None) -> bool:
    """Consulta no máximo uma vez por dia."""
    today = today or date.today()
    return last_check != today.isoformat()
