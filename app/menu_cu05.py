"""Menú CU-05. Cada demostración usa datos nuevos y conserva sus resultados."""

import sys
from pathlib import Path

# Compatibilidad con ejecución directa desde el editor; -m sigue siendo el inicio recomendado.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_escenarios as escenarios
from app.menu_comun import ejecutar_menu


def demo_camino_feliz():
    return escenarios.cu05(1)


def demo_concurrencia():
    return escenarios.cu05(2)


def demo_falla_neo4j_y_rollback():
    return escenarios.cu05(3)


def demo_falla_mongo_y_rollback():
    return escenarios.cu05(4)


def menu():
    return ejecutar_menu(
        "CU-05",
        [
            ("Rescate con paquetes y trazabilidad completos", demo_camino_feliz),
            ("Rescates concurrentes: un reemplazo, un ganador", demo_concurrencia),
            ("Falla Neo4j y compensación", demo_falla_neo4j_y_rollback),
            ("Falla MongoDB y compensación", demo_falla_mongo_y_rollback),
            ("Falla Redis final y compensación", lambda: escenarios.cu05(5)),
            ("Falla en transferencia parcial", lambda: escenarios.cu05(6)),
        ],
        7,
    )


if __name__ == "__main__":
    menu()
