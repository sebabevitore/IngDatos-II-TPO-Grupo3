"""Menú CU-04. Cada demostración usa datos nuevos y conserva sus resultados."""

import sys
from pathlib import Path

# Compatibilidad con ejecución directa desde el editor; -m sigue siendo el inicio recomendado.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_escenarios as escenarios
from app.menu_comun import ejecutar_menu


def demo_sin_desvio():
    return escenarios.cu04(1)


def demo_con_desvio():
    return escenarios.cu04(2)


def demo_sin_historico():
    return escenarios.cu04(3)


def menu():
    return ejecutar_menu(
        "CU-04",
        [
            ("Sin desvío, con históricos reales de tramo", demo_sin_desvio),
            ("Con desvío", demo_con_desvio),
            ("Sin histórico: usar tiempo planificado", demo_sin_historico),
        ],
        4,
    )


if __name__ == "__main__":
    menu()
