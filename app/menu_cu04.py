import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.telemetria import registrar_telemetria
from app.eta import calcular_eta_y_desvio

VIAJE_ID = "VIAJE-PRUEBA-ETA"
PATENTE = "AA111AA"


def _registrar_posicion(latitud, longitud):
    ok, resultado = registrar_telemetria({
        "id_evento": str(uuid4()),
        "vehiculo_patente": PATENTE,
        "fecha_hora": datetime.now(timezone.utc).isoformat(),
        "latitud": latitud,
        "longitud": longitud,
        "velocidad": 40,
        "estado_vehiculo": "EN_RUTA",
        "viaje_id": VIAJE_ID,
    })
    print("Telemetría registrada:", ok, resultado.get("motivo_estado_redis", resultado))


def demo_sin_desvio():
    print("\n--- 1. ESCENARIO: Vehículo sobre la ruta planificada (sin desvío) ---")
    _registrar_posicion(-34.601, -58.401)  # muy cerca de P-1
    resultado = calcular_eta_y_desvio(VIAJE_ID)
    print("Resultado:", resultado)


def demo_con_desvio():
    print("\n--- 2. ESCENARIO: Vehículo alejado de la ruta planificada (con desvío) ---")
    _registrar_posicion(-34.605, -58.405)  # 720m de P-1, supera el umbral
    resultado = calcular_eta_y_desvio(VIAJE_ID)
    print("Resultado:", resultado)


def demo_sin_historico():
    print("\n--- 3. ESCENARIO: Tramo sin historial en Cassandra (usa lo planificado) ---")
    _registrar_posicion(-34.61, -58.42)  # cerca de P-2, yendo hacia P-3 (T-2-3, sin historial cargado)
    resultado = calcular_eta_y_desvio(VIAJE_ID)
    print("Resultado:", resultado)


def menu():
    while True:
        print("\n=============================================================")
        print("   TPO - CU-04: ETA y desvíos (Redis + Neo4j + Cassandra)")
        print("=============================================================")
        print("1. Escenario sin desvío")
        print("2. Escenario con desvío")
        print("3. Escenario sin historial en Cassandra (usa tiempo planificado)")
        print("4. Salir")
        opc = input("\nSeleccione una opción (1-4): ").strip()

        if opc == "1":
            demo_sin_desvio()
        elif opc == "2":
            demo_con_desvio()
        elif opc == "3":
            demo_sin_historico()
        elif opc == "4":
            print("Saliendo...")
            break
        else:
            print("Opción inválida.")


if __name__ == "__main__":
    menu()