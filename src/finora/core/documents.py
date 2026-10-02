"""CPF e CNPJ: limpar, validar (dígitos verificadores) e formatar."""
import re


def digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def _cpf_ok(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        total = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (total * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def _cnpj_ok(d: str) -> bool:
    if len(d) != 14 or d == d[0] * 14:
        return False
    for n in (12, 13):
        weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][13 - n:]
        total = sum(int(d[i]) * weights[i] for i in range(n))
        check = 11 - total % 11
        if (0 if check >= 10 else check) != int(d[n]):
            return False
    return True


def is_valid(text: str, person_type: str) -> bool:
    d = digits(text)
    return _cpf_ok(d) if person_type == "PF" else _cnpj_ok(d)


def fmt(text: str | None) -> str:
    """'12345678909' -> '123.456.789-09'; 14 dígitos viram CNPJ. Outros tamanhos ficam como estão."""
    d = digits(text)
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return text or ""
