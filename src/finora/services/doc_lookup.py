"""Autopreencher contato: dados públicos do CNPJ (Receita Federal) e endereço pelo CEP, via BrasilAPI.

CPF não tem consulta pública (dados pessoais protegidos pela LGPD): o app só confere os dígitos.
"""
from dataclasses import dataclass, field

from finora.core import documents

API = "https://brasilapi.com.br/api"
TIMEOUT = 10


@dataclass(frozen=True)
class CompanyData:
    name: str                          # razão social
    trade_name: str                    # nome fantasia
    status: str                        # situação cadastral (ATIVA, BAIXADA…)
    details: dict = field(default_factory=dict)    # phone, email, zip_code, address, city, state


@dataclass(frozen=True)
class AddressData:
    zip_code: str
    address: str
    city: str
    state: str


def _get(url: str, not_found: str) -> dict:
    import requests
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "IGNF-Finora"})
    except Exception as exc:
        raise ValueError("Não consegui consultar agora. Confira a internet e tente de novo.") from exc
    if resp.status_code in (400, 404):
        raise ValueError(not_found)
    if resp.status_code == 429:
        raise ValueError("Muitas consultas seguidas. Espere um minuto e tente de novo.")
    if resp.status_code >= 400:
        raise ValueError("O serviço de consulta está fora do ar. Tente mais tarde ou preencha à mão.")
    try:
        return resp.json()
    except ValueError as exc:
        raise ValueError("Resposta inválida do serviço de consulta.") from exc


def _phone(raw: str | None) -> str:
    d = documents.digits(raw or "")
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    return (raw or "").strip()


def _join(*parts) -> str:
    return ", ".join(p.strip() for p in parts if p and str(p).strip())


def _title(text: str | None) -> str:
    """'RUA DAS FLORES' -> 'Rua das Flores' (preposições em minúsculas)."""
    small = {"da", "das", "de", "do", "dos", "e"}
    words = (text or "").strip().lower().split()
    return " ".join(w if i and w in small else w.capitalize() for i, w in enumerate(words))


def cnpj(number: str) -> CompanyData:
    d = documents.digits(number)
    if not documents.is_valid(d, "PJ"):
        raise ValueError("CNPJ inválido. Confira os números.")
    data = _get(f"{API}/cnpj/v1/{d}", "CNPJ não encontrado na Receita Federal.")
    cep = documents.digits(str(data.get("cep") or ""))
    details = {
        "phone": _phone(data.get("ddd_telefone_1")),
        "email": (data.get("email") or "").strip().lower(),
        "zip_code": f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else "",
        "address": _join(f"{_title(data.get('descricao_tipo_de_logradouro'))} {_title(data.get('logradouro'))}",
                         data.get("numero"), _title(data.get("complemento")), _title(data.get("bairro")))[:200],
        "city": _title(data.get("municipio"))[:80],
        "state": (data.get("uf") or "").strip().upper()[:2],
    }
    return CompanyData((data.get("razao_social") or "").strip(), (data.get("nome_fantasia") or "").strip(),
                       (data.get("descricao_situacao_cadastral") or "").strip(),
                       {k: v for k, v in details.items() if v})


def cep(number: str) -> AddressData:
    d = documents.digits(number)
    if len(d) != 8:
        raise ValueError("CEP inválido. Use 8 números, ex.: 13010-050.")
    data = _get(f"{API}/cep/v2/{d}", "CEP não encontrado.")
    return AddressData(f"{d[:5]}-{d[5:]}", _join(data.get("street"), data.get("neighborhood"))[:200],
                       (data.get("city") or "").strip(), (data.get("state") or "").strip().upper())
