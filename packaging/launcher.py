"""Ponto de entrada do executável empacotado (PyInstaller)."""
import sys

from finora.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
