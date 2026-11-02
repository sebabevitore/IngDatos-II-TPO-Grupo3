"""Menú CU-07. Cada demostración usa datos nuevos y conserva sus resultados."""

import sys
from pathlib import Path

# Compatibilidad con ejecución directa desde el editor; -m sigue siendo el inicio recomendado.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_escenarios as escenarios
from app.menu_comun import ejecutar_menu


def demo_desvio_exitoso():
    return escenarios.cu07(1)


def demo_sin_salida():
    return escenarios.cu07(2)


def menu():
    return ejecutar_menu(
        "CU-07",
        [
            ("Camino alternativo en una red propia", demo_desvio_exitoso),
            ("Red realmente sin salida al bloquear el punto", demo_sin_salida),
        ],
        3,
    )


if __name__ == "__main__":
    menu()
