"""
Menú interactivo y de prueba para el Caso de Uso 2: Ingesta de telemetría (Cassandra + Redis).
Permite ejecutar y verificar todos los escenarios exigidos por la consigna (Sección 4, 5 y 8).
"""

import os
import sys
import json
from uuid import uuid4
from datetime import datetime, timezone

# Permite ejecutar directamente el archivo con el botón de Play del editor
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.telemetria import registrar_telemetria


def demo_ingesta_gps():
    print("\n--- 1. ESCENARIO: Ingesta de telemetría en tiempo real (Cassandra + Redis) ---")
    ahora = datetime.now(timezone.utc).isoformat()
    medicion = {
        "id_evento": str(uuid4()),
        "vehiculo_patente": "AB123CD",
        "fecha_hora": ahora,
        "latitud": -34.6037,
        "longitud": -58.3816,
        "velocidad": 45.5,
        "estado_vehiculo": "EN_MOVIMIENTO",
        "viaje_id": "VIAJE-1001",
    }
    print(f"Enviando medición GPS para vehículo {medicion['vehiculo_patente']} en viaje {medicion['viaje_id']}...")
    exito, resultado = registrar_telemetria(medicion)
    print("Éxito:", exito)
    print("Resultado:", json.dumps(resultado, indent=2, ensure_ascii=False, default=str))


def demo_medicion_desordenada():
    print("\n--- 2. ESCENARIO: Paquete GPS desordenado / antiguo rechazado por script Lua en Redis ---")
    medicion_antigua = {
        "id_evento": str(uuid4()),
        "vehiculo_patente": "AB123CD",
        "fecha_hora": "2026-10-01T10:00:00Z",
        "latitud": -34.6100,
        "longitud": -58.3900,
        "velocidad": 20.0,
        "estado_vehiculo": "DETENIDO",
        "viaje_id": "VIAJE-1001",
    }
    print("Enviando medición antigua (fecha anterior a la actual)...")
    exito, resultado = registrar_telemetria(medicion_antigua)
    print("Éxito:", exito)
    print("Resultado:", json.dumps(resultado, indent=2, ensure_ascii=False, default=str))


def menu_cu02():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--all", "-a", "all"]:
            print("\n--- Ejecutando todos los escenarios de CU-02 ---")
            demo_ingesta_gps()
            demo_medicion_desordenada()
            return
        elif arg in ["1", "--demo1"]:
            demo_ingesta_gps()
            return
        elif arg in ["2", "--demo2"]:
            demo_medicion_desordenada()
            return

    while True:
        print("\n=============================================================")
        print("   TPO - CU-02: Ingesta de Telemetría (Cassandra + Redis)")
        print("=============================================================")
        print("1. Camino feliz: Ingesta de telemetría y actualización en Redis")
        print("2. Descarte por desorden temporal: Medición antigua rechazada en Redis")
        print("3. Volver al menú principal")
        opc = input("\nSeleccione una opción (1-3): ").strip()

        if opc == "1":
            try:
                demo_ingesta_gps()
            except Exception as e:
                print(f"[ERROR] {e}")
        elif opc == "2":
            try:
                demo_medicion_desordenada()
            except Exception as e:
                print(f"[ERROR] {e}")
        elif opc in ["3", "0", "salir", "exit"]:
            break
        else:
            print("Opción inválida.")


if __name__ == "__main__":
    menu_cu02()

