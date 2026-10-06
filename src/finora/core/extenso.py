"""Valor por extenso em português (para recibos): Decimal('1250.40') ->
'mil duzentos e cinquenta reais e quarenta centavos'."""
from decimal import Decimal, ROUND_HALF_UP

_UNITS = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
          "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_TENS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_HUNDREDS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
             "oitocentos", "novecentos"]
# (singular, plural) da moeda e dos centavos
_CURRENCY = {
    "BRL": (("real", "reais"), ("centavo", "centavos")),
    "USD": (("dólar", "dólares"), ("centavo", "centavos")),
    "EUR": (("euro", "euros"), ("cêntimo", "cêntimos")),
    "GBP": (("libra", "libras"), ("pêni", "pence")),
}
_SCALES = [("", ""), ("mil", "mil"), ("milhão", "milhões"), ("bilhão", "bilhões"), ("trilhão", "trilhões")]


def _below_1000(n: int) -> str:
    if n == 100:
        return "cem"
    h, rest = divmod(n, 100)
    parts = [_HUNDREDS[h]] if h else []
    if rest:
        if rest < 20:
            parts.append(_UNITS[rest])
        else:
            t, u = divmod(rest, 10)
            parts.append(_TENS[t] + (f" e {_UNITS[u]}" if u else ""))
    return " e ".join(parts)


def number(n: int) -> str:
    """Inteiro por extenso: 1250 -> 'mil duzentos e cinquenta'."""
    if n == 0:
        return "zero"
    groups = []
    i = 0
    while n:
        n, g = divmod(n, 1000)
        if g:
            groups.append((i, g))
        i += 1
    groups.reverse()                                   # do maior para o menor
    words = []
    for k, (scale, g) in enumerate(groups):
        if scale == 1:
            w = "mil" if g == 1 else f"{_below_1000(g)} mil"
        elif scale >= 2:
            w = f"{_below_1000(g)} {_SCALES[scale][0] if g == 1 else _SCALES[scale][1]}"
        else:
            w = _below_1000(g)
        if k > 0:
            # "e" antes do último grupo quando ele é < 100 ou centena redonda: "mil e duzentos", "mil e cinquenta"
            last = k == len(groups) - 1
            words.append(" e " if last and (g < 100 or g % 100 == 0) else " ")
        words.append(w)
    return "".join(words)


def money(value: Decimal, currency: str = "BRL") -> str:
    value = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value < 0:
        raise ValueError("Valor por extenso só para valores positivos.")
    (unit_s, unit_p), (cent_s, cent_p) = _CURRENCY.get(currency, _CURRENCY["BRL"])
    whole = int(value)
    cents = int((value - whole) * 100)
    parts = []
    if whole:
        w = number(whole)
        exact_scale = whole >= 1_000_000 and whole % 1_000_000 == 0   # "um milhão DE reais"
        parts.append(f"{w} {'de ' if exact_scale else ''}{unit_s if whole == 1 else unit_p}")
    if cents:
        parts.append(f"{number(cents)} {cent_s if cents == 1 else cent_p}")
    if not parts:
        return f"zero {unit_p}"
    return " e ".join(parts)
