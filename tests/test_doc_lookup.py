import pytest
import requests

from finora.services import doc_lookup

CNPJ = "11.222.333/0001-81"
RECEITA = {"razao_social": "ENERGIA PAULISTA S.A.", "nome_fantasia": "ENEL", "descricao_situacao_cadastral": "ATIVA",
           "ddd_telefone_1": "1133334444", "email": "CONTATO@ENEL.COM", "cep": "01310100",
           "descricao_tipo_de_logradouro": "AVENIDA", "logradouro": "PAULISTA", "numero": "1000",
           "complemento": "ANDAR 5", "bairro": "BELA VISTA", "municipio": "SAO PAULO", "uf": "SP"}


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data or {}

    def json(self):
        return self._data


def test_cnpj_preenche_dados_da_receita(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", lambda url, **k: calls.append(url) or Resp(200, RECEITA))
    d = doc_lookup.cnpj(CNPJ)
    assert calls == ["https://brasilapi.com.br/api/cnpj/v1/11222333000181"]
    assert (d.name, d.trade_name, d.status) == ("ENERGIA PAULISTA S.A.", "ENEL", "ATIVA")
    assert d.details == {"phone": "(11) 3333-4444", "email": "contato@enel.com", "zip_code": "01310-100",
                         "address": "Avenida Paulista, 1000, Andar 5, Bela Vista", "city": "Sao Paulo",
                         "state": "SP"}


def test_cep_preenche_endereco(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, **k: Resp(200, {
        "street": "Rua Barão de Jaguara", "neighborhood": "Centro", "city": "Campinas", "state": "SP"}))
    a = doc_lookup.cep("13015-002")
    assert (a.zip_code, a.address, a.city, a.state) == ("13015-002", "Rua Barão de Jaguara, Centro", "Campinas", "SP")


@pytest.mark.parametrize("status, msg", [(404, "não encontrado"), (429, "Espere"), (500, "fora do ar")])
def test_erros_do_servico(monkeypatch, status, msg):
    monkeypatch.setattr(requests, "get", lambda url, **k: Resp(status))
    with pytest.raises(ValueError, match=msg):
        doc_lookup.cnpj(CNPJ)


def test_sem_internet_e_numeros_invalidos(monkeypatch):
    def offline(*a, **k):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(requests, "get", offline)
    with pytest.raises(ValueError, match="internet"):
        doc_lookup.cep("13015002")
    with pytest.raises(ValueError, match="CNPJ inválido"):
        doc_lookup.cnpj("11.222.333/0001-80")
    with pytest.raises(ValueError, match="CEP inválido"):
        doc_lookup.cep("123")
