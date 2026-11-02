"""Menú CU-06. Cada demostración usa datos nuevos y conserva sus resultados."""

import sys
from pathlib import Path

# Compatibilidad con ejecución directa desde el editor; -m sigue siendo el inicio recomendado.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_escenarios as escenarios
from app.menu_comun import ejecutar_menu


def demo_camino_feliz():
    return escenarios.cu06(1)


def demo_concurrencia_doble_entrega():
    return escenarios.cu06(2)


def demo_falla_cassandra_y_rollback():
    return escenarios.cu06(3)


def demo_falla_mongo_y_rollback():
    return escenarios.cu06(4)


def menu():
    return ejecutar_menu(
        "CU-06",
        [
            ("Entrega con viaje, POD y métricas coherentes", demo_camino_feliz),
            (
                "Doble confirmación: un ganador y un POD",
                demo_concurrencia_doble_entrega,
            ),
            ("Falla Cassandra y compensación", demo_falla_cassandra_y_rollback),
            ("Falla MongoDB y compensación", demo_falla_mongo_y_rollback),
            ("Falla Redis final y compensación", lambda: escenarios.cu06(5)),
        ],
        6,
    )


if __name__ == "__main__":
    menu()
