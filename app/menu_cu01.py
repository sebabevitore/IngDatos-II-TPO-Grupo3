"""Menú CU-01. Cada demostración usa datos nuevos y conserva sus resultados."""

import sys
from pathlib import Path

# Compatibilidad con ejecución directa desde el editor; -m sigue siendo el inicio recomendado.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_escenarios as escenarios
from app.menu_comun import ejecutar_menu


def demo_camino_feliz():
    return escenarios.cu01_feliz()


def demo_concurrencia():
    return escenarios.cu01_concurrencia()


def demo_falla_y_rollback():
    return escenarios.cu01_falla()


def menu_cu01():
    return ejecutar_menu(
        "CU-01",
        [
            ("Planificación persistente con asignaciones", demo_camino_feliz),
            ("Dos coordinadores compiten por el mismo viaje", demo_concurrencia),
            ("Falla en MongoDB y compensación comprobada", demo_falla_y_rollback),
        ],
        4,
    )


menu = menu_cu01

if __name__ == "__main__":
    menu_cu01()
