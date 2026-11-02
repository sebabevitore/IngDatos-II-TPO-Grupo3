"""Menú CU-02. Cada demostración usa datos nuevos y conserva sus resultados."""

import sys
from pathlib import Path

# Compatibilidad con ejecución directa desde el editor; -m sigue siendo el inicio recomendado.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_escenarios as escenarios
from app.menu_comun import ejecutar_menu


def demo_ingesta_gps():
    return escenarios.cu02_actual()


def demo_medicion_desordenada():
    return escenarios.cu02_antigua()


def demo_simulacion_50():
    return escenarios.cu02_simulacion()


def menu_cu02():
    return ejecutar_menu(
        "CU-02",
        [
            ("Ingesta GPS en los tres motores", demo_ingesta_gps),
            ("Lectura antigua con estado reciente propio", demo_medicion_desordenada),
            ("Simular 50 vehículos concurrentes mediante CU02", demo_simulacion_50),
        ],
        4,
    )


menu = menu_cu02

if __name__ == "__main__":
    menu_cu02()
