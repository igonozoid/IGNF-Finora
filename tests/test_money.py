from decimal import Decimal as D

import pytest

from finora.core import money


@pytest.mark.parametrize("text, expected", [
    ("1.234,56", D("1234.56")), ("1234,5", D("1234.50")), ("-50", D("-50.00")),
    ("− R$ 1.000,00", D("-1000.00")), ("R$ 10", D("10.00")), ("US$ 3,5", D("3.50")),
    ("12.5", D("12.50")), ("1.234", D("1234.00")), ("1.234.567", D("1234567.00")),
    ("", D("0.00")), ("0,005", D("0.01")),
])
def test_parse(text, expected):
    assert money.parse(text) == expected


@pytest.mark.parametrize("text", ["abc", "1,2,3", "--5", "1-2"])
def test_parse_invalido(text):
    with pytest.raises(ValueError):
        money.parse(text)


def test_fmt():
    assert money.fmt(D("-1234.5")) == "− R$ 1.234,50"
    assert money.fmt(D("0"), "USD") == "US$ 0,00"
    assert money.fmt(D("1000000")) == "R$ 1.000.000,00"
