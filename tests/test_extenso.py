from decimal import Decimal as D

import pytest

from finora.core import extenso


@pytest.mark.parametrize("n, words", [
    (0, "zero"), (1, "um"), (10, "dez"), (16, "dezesseis"), (21, "vinte e um"), (100, "cem"), (101, "cento e um"),
    (115, "cento e quinze"), (200, "duzentos"), (999, "novecentos e noventa e nove"),
    (1000, "mil"), (1001, "mil e um"), (1050, "mil e cinquenta"), (1100, "mil e cem"), (1200, "mil e duzentos"),
    (1250, "mil duzentos e cinquenta"), (2000, "dois mil"), (21345, "vinte e um mil trezentos e quarenta e cinco"),
    (100000, "cem mil"), (150000, "cento e cinquenta mil"),
    (1_000_000, "um milhão"), (2_500_000, "dois milhões e quinhentos mil"),
    (1_234_567, "um milhão duzentos e trinta e quatro mil quinhentos e sessenta e sete"),
    (3_000_000_000, "três bilhões"),
])
def test_numero(n, words):
    assert extenso.number(n) == words


@pytest.mark.parametrize("value, words", [
    ("1250.40", "mil duzentos e cinquenta reais e quarenta centavos"),
    ("1", "um real"), ("1.01", "um real e um centavo"), ("0.50", "cinquenta centavos"), ("0", "zero reais"),
    ("100", "cem reais"), ("1000000", "um milhão de reais"), ("2000000.10", "dois milhões de reais e dez centavos"),
    ("1500000", "um milhão e quinhentos mil reais"), ("350", "trezentos e cinquenta reais"),
])
def test_valor_em_reais(value, words):
    assert extenso.money(D(value)) == words


def test_outras_moedas_e_negativo():
    assert extenso.money(D("2.5"), "USD") == "dois dólares e cinquenta centavos"
    assert extenso.money(D("1"), "EUR") == "um euro"
    with pytest.raises(ValueError):
        extenso.money(D("-1"))
