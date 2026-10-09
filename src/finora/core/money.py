"""Valores monetários: sempre Decimal, nunca float."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# código -> (símbolo, nome para o usuário). As que a pessoa cadastra (services/currencies) entram aqui ao abrir.
CURRENCIES = {
    "BRL": ("R$", "Real brasileiro"),
    "USD": ("US$", "Dólar americano"),
    "EUR": ("€", "Euro"),
    "GBP": ("£", "Libra esterlina"),
    "ARS": ("AR$", "Peso argentino"),
    "UYU": ("UY$", "Peso uruguaio"),
    "PYG": ("₲", "Guarani paraguaio"),
    "CLP": ("CL$", "Peso chileno"),
    "BOB": ("Bs", "Boliviano"),
    "PEN": ("S/", "Sol peruano"),
    "COP": ("CO$", "Peso colombiano"),
    "MXN": ("MX$", "Peso mexicano"),
    "CAD": ("CA$", "Dólar canadense"),
    "AUD": ("AU$", "Dólar australiano"),
    "CHF": ("CHF", "Franco suíço"),
    "JPY": ("¥", "Iene japonês"),
    "CNY": ("CN¥", "Yuan chinês"),
}
BUILTIN = frozenset(CURRENCIES)


def register(code: str, symbol: str, name: str) -> None:
    """Moeda cadastrada pela pessoa (fica no banco; ver services/currencies)."""
    CURRENCIES[code] = (symbol, name)


def unregister(code: str) -> None:
    if code not in BUILTIN:
        CURRENCIES.pop(code, None)

CENT = Decimal("0.01")
MINUS = "−"  # sinal de menos tipográfico, como no mockup


def symbol(currency: str) -> str:
    return CURRENCIES.get(currency, (currency, ""))[0]


def parse(text: str) -> Decimal:
    """Lê um valor digitado no padrão brasileiro ('1.234,56', '-50', '10,5').

    Sem vírgula, o ponto só vira decimal se tiver 1 ou 2 casas ('12.5'); senão é
    separador de milhar ('1.234'). Texto vazio vale zero. Levanta ValueError se inválido.
    """
    s = text.strip().replace(MINUS, "-").replace(" ", "")
    for sym in sorted((c[0] for c in CURRENCIES.values()), key=len, reverse=True):
        s = s.replace(sym, "")
    if not s or s == "-":
        return Decimal("0.00")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif not re.fullmatch(r"-?\d+\.\d{1,2}", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        raise ValueError(f"valor inválido: {text!r}")
    try:
        return Decimal(s).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as e:
        raise ValueError(f"valor inválido: {text!r}") from e


def fmt(value: Decimal, currency: str = "BRL") -> str:
    """Decimal('-1234.5') -> '− R$ 1.234,50'."""
    v = Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    body = f"{abs(v):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{MINUS + ' ' if v < 0 else ''}{symbol(currency)} {body}"
