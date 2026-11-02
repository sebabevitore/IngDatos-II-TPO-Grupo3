"""Menú CU-03. Cada demostración usa datos nuevos y conserva sus resultados."""

import sys
from pathlib import Path

# Compatibilidad con ejecución directa desde el editor; -m sigue siendo el inicio recomendado.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_escenarios as escenarios
from app.menu_comun import ejecutar_menu


def demo_camino_feliz_exceso_velocidad():
    return escenarios.cu03(1)


def demo_anomalia_sostenida():
    return escenarios.cu03(2)


def demo_falla_cassandra_y_rollback():
    return escenarios.cu03(3)


def demo_falla_redis_y_reconciliacion():
    return escenarios.cu03(4)


def demo_reconstruir_redis_desde_cero():
    return escenarios.cu03(5)


def menu():
    return ejecutar_menu(
        "CU-03",
        [
            ("Detectar exceso de velocidad", demo_camino_feliz_exceso_velocidad),
            ("Deduplicar y conservar el ID durable", demo_anomalia_sostenida),
            ("Falla Cassandra y rollback del claim", demo_falla_cassandra_y_rollback),
            (
                "Falla Redis y reconciliación de la alerta propia",
                demo_falla_redis_y_reconciliacion,
            ),
            (
                "Pérdida de una alerta de prueba y recuperación sin FLUSHALL",
                demo_reconstruir_redis_desde_cero,
            ),
        ],
        6,
    )


if __name__ == "__main__":
    menu()
