import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.conexiones import conectar_cassandra
from app.repositorio_eta_cassandra import (
    registrar_duracion_tramo,
    obtener_tiempos_historicos_tramo,
)


def main():
    cluster, sesion = conectar_cassandra()
    try:
        print("Cargando duraciones de prueba para el tramo T-1-2...")
        registrar_duracion_tramo(sesion, "T-1-2", "VIAJE-HIST-1", 9.5)
        registrar_duracion_tramo(sesion, "T-1-2", "VIAJE-HIST-2", 7.8)
        registrar_duracion_tramo(sesion, "T-1-2", "VIAJE-HIST-3", 10.2)

        print("\n--- Tiempos históricos del tramo T-1-2 ---")
        tiempos = obtener_tiempos_historicos_tramo(sesion, "T-1-2")
        print(tiempos)

    finally:
        cluster.shutdown()


if __name__ == "__main__":
    main()