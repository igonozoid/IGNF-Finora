"""Guardar a senha do servidor no finora.ini sem deixá-la em texto puro.

Windows: DPAPI (só o mesmo usuário do Windows, neste computador, consegue abrir). Outros sistemas: apenas
codificada (base64) — o arquivo fica na pasta de dados do usuário; não é proteção forte.
"""
import base64
import sys

PREFIX_DPAPI = "dpapi:"
PREFIX_B64 = "b64:"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = (fn(ctypes.byref(blob_in), "IGNF Finora", None, None, None, 0x1, ctypes.byref(blob_out)) if protect
          else fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)))
    if not ok:
        raise OSError("DPAPI falhou")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(text: str) -> str:
    if not text:
        return ""
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        try:
            return PREFIX_DPAPI + base64.b64encode(_dpapi(raw, True)).decode()
        except OSError:
            pass
    return PREFIX_B64 + base64.b64encode(raw).decode()


def unprotect(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith(PREFIX_DPAPI):
        try:
            return _dpapi(base64.b64decode(stored[len(PREFIX_DPAPI):]), False).decode("utf-8")
        except (OSError, ValueError):
            return ""                       # outro usuário/computador: pede a senha de novo
    if stored.startswith(PREFIX_B64):
        return base64.b64decode(stored[len(PREFIX_B64):]).decode("utf-8")
    return stored
