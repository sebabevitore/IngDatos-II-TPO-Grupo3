"""
Script interactivo y de prueba para el Caso de Uso 3: Detección de anomalías (Cassandra + Redis).
Permite ejecutar y verificar todos los escenarios exigidos por la consigna (Sección 4, 5 y 8).
"""

import uuid
from datetime import datetime, timezone
import json

from app.anomalias import procesar_anomalias_telemetria
from app.fallas import InyectorFallas, FallaSimuladaError
from app.recuperacion_anomalias import reconciliar_anomalias
from app.conexiones import conectar_cassandra, conectar_redis


def crear_medicion(
    patente="AA123BB",
    viaje_id="VIAJE-101",
    velocidad=70.0,
    estado="EN_MOVIMIENTO",
    latitud=-34.6037,
    longitud=-58.3816
):
    ahora = datetime.now(timezone.utc).isoformat()
    return {
        "id_evento": str(uuid.uuid4()),
        "vehiculo_patente": patente,
        "viaje_id": viaje_id,
        "fecha_hora": ahora,
        "latitud": latitud,
        "longitud": longitud,
        "velocidad": velocidad,
        "estado_vehiculo": estado
    }


def demo_camino_feliz_exceso_velocidad():
    print("\n--- 1. ESCENARIO: Camino feliz - Exceso de velocidad (105 km/h) ---")
    datos = crear_medicion(velocidad=105.0)
    print(f"Enviando medición de telemetría: {datos['vehiculo_patente']} a {datos['velocidad']} km/h...")
    res = procesar_anomalias_telemetria(datos)
    print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))


def demo_anomalia_sostenida():
    print("\n--- 2. ESCENARIO: Deduplicación por anomalía sostenida (5 lecturas consecutivas) ---")
    patente = "AA123BB"
    for i in range(1, 6):
        datos = crear_medicion(patente=patente, velocidad=110.0 + i)
        print(f"\n[Lectura {i}] Vehículo {patente} a {datos['velocidad']} km/h...")
        res = procesar_anomalias_telemetria(datos)
        print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))


def demo_falla_cassandra_y_rollback():
    print("\n--- 3. ESCENARIO: Falla inducida en Cassandra -> Rollback en Redis ---")
    datos = crear_medicion(patente="AF123PQ", velocidad=120.0)
    inyector = InyectorFallas("CASSANDRA_WRITE")

    print("Ejecutando con falla forzada en 'CASSANDRA_WRITE'...")
    try:
        procesar_anomalias_telemetria(datos, inyector=inyector)
        print("ERROR: La falla no se produjo.")
    except Exception as e:
        print(f"\n[OK] Falla interceptada correctamente: {e}")

    # Verificar que el claim de Redis se haya liberado (compensación exitosa)
    cliente_redis = conectar_redis()
    clave = f"alerta:activa:AF123PQ:EXCESO_VELOCIDAD"
    existe = cliente_redis.exists(clave)
    cliente_redis.close()
    print(f"Comprobación de Rollback: ¿Existe la clave en Redis? {'SÍ (MAL)' if existe else 'NO (ROLLBACK EXITOSO)'}")


def demo_falla_redis_y_reconciliacion():
    print("\n--- 4. ESCENARIO: Falla en confirmación de Redis -> Reconciliación ---")
    datos = crear_medicion(patente="AB123CD", velocidad=130.0)
    inyector = InyectorFallas("REDIS_CONFIRM")

    print("Ejecutando con falla forzada en 'REDIS_CONFIRM'...")
    try:
        procesar_anomalias_telemetria(datos, inyector=inyector)
    except Exception as e:
        print(f"[Aviso esperado] {e}")

    print("\nEjecutando proceso de reconciliación...")
    resultado_rec = reconciliar_anomalias()
    print("Resultado Reconciliador:", json.dumps(resultado_rec, indent=2, ensure_ascii=False))


def demo_reconstruir_redis_desde_cero():
    print("\n--- 5. ESCENARIO: Caída total de Redis (FLUSHALL) y reconstrucción desde Cassandra ---")
    cliente_redis = conectar_redis()
    print("Vaciando Redis (simulación de pérdida total de claves en memoria)...")
    cliente_redis.flushall()
    cliente_redis.close()

    print("Ejecutando reconciliación desde la fuente de verdad (Cassandra)...")
    res = reconciliar_anomalias()
    print("Resultado Reconciliador:", json.dumps(res, indent=2, ensure_ascii=False))


def menu():
    while True:
        print("\n==================================================")
        print("   TPO - CU-03: Detección de anomalías (Cassandra + Redis)")
        print("==================================================")
        print("1. Camino feliz: Detectar exceso de velocidad")
        print("2. Deduplicación: Anomalía sostenida (varias lecturas)")
        print("3. Demostración de Falla: Error en Cassandra y Rollback")
        print("4. Demostración de Falla: Error en Redis y Reconciliación")
        print("5. Resiliencia: Vaciar Redis y reconstruir desde Cassandra")
        print("6. Salir")
        opc = input("\nSeleccione una opción (1-6): ").strip()

        if opc == "1":
            demo_camino_feliz_exceso_velocidad()
        elif opc == "2":
            demo_anomalia_sostenida()
        elif opc == "3":
            demo_falla_cassandra_y_rollback()
        elif opc == "4":
            demo_falla_redis_y_reconciliacion()
        elif opc == "5":
            demo_reconstruir_redis_desde_cero()
        elif opc == "6":
            print("Saliendo...")
            break
        else:
            print("Opción inválida.")


if __name__ == "__main__":
    menu()

