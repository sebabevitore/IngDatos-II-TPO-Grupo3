"""Acceso compatible a la demostración corregida de CU01."""

import sys
from pathlib import Path

# Compatibilidad con ejecución directa desde el editor; -m sigue siendo el inicio recomendado.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_escenarios


def main():
    return demo_escenarios.cu01_feliz()


if __name__ == "__main__":
    main()
