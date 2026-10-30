"""
Menú interactivo de prueba para el Caso de Uso 6: Confirmación de entrega (MongoDB + Cassandra + Redis).
Permite ejecutar y verificar todos los escenarios exigidos por la consigna (Sección 4, 5 y 8).
"""

import os
import sys

# Permite ejecutar directamente el archivo con el botón de Play del editor
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from app.conexiones import (
    conectar_mongodb,
    conectar_redis,
    conectar_cassandra
)
from app.fallas import InyectorFallas
from app.entrega import confirmar_entrega_paquete
from app.repositorio_entrega_mongo import (
    asegurar_paquete_para_entrega_mongo,
    consultar_paquete_mongo
)
from app.repositorio_entrega_cassandra import consultar_entregas_viaje_cassandra
from app.repositorio_entrega_redis import obtener_progreso_viaje_redis


def preparar_paquete_base(paquete_codigo="PAQ-E01", viaje_id="VIAJE-ENTREGA-01"):
    """Asegura datos limpios en MongoDB y Redis para la prueba."""
    mongo = conectar_mongodb()
    try:
        asegurar_paquete_para_entrega_mongo(
            mongo,
            paquete_codigo=paquete_codigo,
            viaje_id=viaje_id
        )
    finally:
        mongo.close()

    redis_cli = conectar_redis()
    try:
        redis_cli.delete(
            f"lock:entrega:paquete:{paquete_codigo}",
            f"paquete:{paquete_codigo}:estado",
            f"viaje:{viaje_id}:progreso"
        )
    finally:
        redis_cli.close()


def demo_camino_feliz():
    print("\n--- 1. ESCENARIO: Camino feliz - Confirmación de entrega exitosa ---")
    paquete = "PAQ-ENTREGA-OK"
    viaje = "VIAJE-ENTREGA-100"
    patente = "AB123CD"

    print(f"Preparando paquete {paquete} en viaje {viaje}...")
    preparar_paquete_base(paquete, viaje)

    datos = {
        "viaje_id": viaje,
        "paquete_codigo": paquete,
        "vehiculo_patente": patente,
        "fecha_hora": datetime.now(timezone.utc).isoformat(),
        "receptor_nombre": "Carlos Gómez",
        "receptor_dni": "32111222",
        "receptor_vinculo": "TITULAR",
        "latitud": -34.6037,
        "longitud": -58.3816
    }

    print("\nEjecutando confirmación de entrega (Redis -> Cassandra -> MongoDB -> Redis)...")
    res = confirmar_entrega_paquete(datos)
    print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))

    # 1. Verificación en MongoDB
    mongo = conectar_mongodb()
    doc_paq = consultar_paquete_mongo(mongo, paquete)
    mongo.close()
    print("\n[VERIFICACIÓN EN MONGODB]:")
    print(f"  Estado del paquete: {doc_paq.get('estado')}")
    print(f"  Datos del receptor:", doc_paq.get('receptor'))

    # 2. Verificación en Cassandra (POD Legal)
    cluster, sesion = conectar_cassandra()
    dia_actual = datetime.now(timezone.utc).date()
    entregas_cass = consultar_entregas_viaje_cassandra(sesion, viaje, dia_actual)
    cluster.shutdown()
    print("\n[VERIFICACIÓN EN CASSANDRA - HISTÓRICO LEGAL]:")
    print(f"  Eventos POD registrados en Cassandra: {len(entregas_cass)}")
    if entregas_cass:
        print(f"  Último POD:", entregas_cass[-1])

    # 3. Verificación en Redis (Contadores del viaje)
    redis_cli = conectar_redis()
    progreso = obtener_progreso_viaje_redis(redis_cli, viaje)
    redis_cli.close()
    print("\n[VERIFICACIÓN EN REDIS]:")
    print(f"  Progreso en vivo del viaje {viaje}:", progreso)


def demo_concurrencia_doble_entrega():
    print("\n--- 2. ESCENARIO: Idempotencia y concurrencia - Doble confirmación simultánea ---")
    paquete = "PAQ-DOBLE-CONFIRM"
    viaje = "VIAJE-DOBLE-01"
    preparar_paquete_base(paquete, viaje)

    datos1 = {
        "viaje_id": viaje,
        "paquete_codigo": paquete,
        "vehiculo_patente": "AB123CD",
        "fecha_hora": datetime.now(timezone.utc).isoformat(),
        "receptor_nombre": "Intento App Móvil",
        "receptor_dni": "11111111"
    }

    datos2 = {
        "viaje_id": viaje,
        "paquete_codigo": paquete,
        "vehiculo_patente": "AB123CD",
        "fecha_hora": datetime.now(timezone.utc).isoformat(),
        "receptor_nombre": "Intento Call Center",
        "receptor_dni": "22222222"
    }

    print(f"Disparando 2 confirmaciones simultáneas para el mismo paquete {paquete}...")

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(confirmar_entrega_paquete, datos1)
        f2 = executor.submit(confirmar_entrega_paquete, datos2)

        r1 = f1.result()
        r2 = f2.result()

    print("\n[RESPUESTA 1]:", json.dumps(r1, indent=2, ensure_ascii=False))
    print("\n[RESPUESTA 2]:", json.dumps(r2, indent=2, ensure_ascii=False))

    exitos = sum([1 for r in [r1, r2] if r["exito"]])
    print(f"\n[CONTROL DE CONCURRENCIA]: Ganador único = {'SÍ (IDEMPOTENCIA EXITOSA)' if exitos == 1 else 'NO (ERROR)'}")


def demo_falla_cassandra_y_rollback():
    print("\n--- 3. ESCENARIO: Falla inducida en Cassandra -> Rollback en Redis ---")
    paquete = "PAQ-FALLA-CASS"
    viaje = "VIAJE-FALLA-01"
    preparar_paquete_base(paquete, viaje)

    datos = {
        "viaje_id": viaje,
        "paquete_codigo": paquete,
        "vehiculo_patente": "AB123CD",
        "fecha_hora": datetime.now(timezone.utc).isoformat()
    }

    inyector = InyectorFallas("CU06_CASSANDRA")
    print("Ejecutando con fallo forzado en el paso 'CU06_CASSANDRA'...")
    res = confirmar_entrega_paquete(datos, inyector=inyector)
    print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))

    # Comprobar que el lock en Redis fue liberado
    redis_cli = conectar_redis()
    lock_existe = redis_cli.exists(f"lock:entrega:paquete:{paquete}")
    redis_cli.close()
    print(f"Comprobación de Rollback: ¿El lock del paquete en Redis fue liberado? {'SÍ (ROLLBACK EXITOSO)' if not lock_existe else 'NO'}")


def demo_falla_mongo_y_rollback():
    print("\n--- 4. ESCENARIO: Falla inducida en MongoDB -> Rollback en Cassandra y Redis ---")
    paquete = "PAQ-FALLA-MONGO"
    viaje = "VIAJE-FALLA-02"
    preparar_paquete_base(paquete, viaje)

    datos = {
        "viaje_id": viaje,
        "paquete_codigo": paquete,
        "vehiculo_patente": "AB123CD",
        "fecha_hora": datetime.now(timezone.utc).isoformat(),
        "receptor_nombre": "Prueba Falla Mongo"
    }

    inyector = InyectorFallas("CU06_MONGO")
    print("Ejecutando con fallo forzado en el paso 'CU06_MONGO'...")
    res = confirmar_entrega_paquete(datos, inyector=inyector)
    print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))

    # 1. Comprobar que el evento fue eliminado de Cassandra
    cluster, sesion = conectar_cassandra()
    dia_actual = datetime.now(timezone.utc).date()
    entregas_cass = consultar_entregas_viaje_cassandra(sesion, viaje, dia_actual)
    cluster.shutdown()

    paquetes_en_cass = [e["paquete_codigo"] for e in entregas_cass]
    print(f"\n[COMPROBACIÓN EN CASSANDRA]:")
    print(f"  ¿El evento en Cassandra fue deshecho? {'SÍ (ROLLBACK EXITOSO)' if paquete not in paquetes_en_cass else 'NO'}")

    # 2. Comprobar que en MongoDB el paquete sigue EN_TRANSITO
    mongo = conectar_mongodb()
    doc_paq = consultar_paquete_mongo(mongo, paquete)
    mongo.close()
    print(f"\n[COMPROBACIÓN EN MONGODB]:")
    print(f"  Estado del paquete tras rollback: {doc_paq.get('estado')} (esperado: EN_TRANSITO)")


def menu():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--all", "-a", "all"]:
            print("=== EJECUTANDO SUITE COMPLETA DE CASO DE USO 6 ===")
            demo_camino_feliz()
            demo_concurrencia_doble_entrega()
            demo_falla_cassandra_y_rollback()
            demo_falla_mongo_y_rollback()
            print("\n=== TODAS LAS PRUEBAS DE CU-06 FINALIZARON CON ÉXITO ===")
            return
        elif arg in ["1", "--demo1"]:
            demo_camino_feliz()
            return
        elif arg in ["2", "--demo2"]:
            demo_concurrencia_doble_entrega()
            return
        elif arg in ["3", "--demo3"]:
            demo_falla_cassandra_y_rollback()
            return
        elif arg in ["4", "--demo4"]:
            demo_falla_mongo_y_rollback()
            return

    while True:
        print("\n=============================================================")
        print("   TPO - CU-06: Confirmación de entrega (MongoDB + Cassandra + Redis)")
        print("=============================================================")
        print("1. Camino feliz: Confirmación completa exitosa")
        print("2. Concurrencia: Doble confirmación simultánea (Idempotencia)")
        print("3. Demostración de Falla: Error en Cassandra y Rollback en Redis")
        print("4. Demostración de Falla: Error en MongoDB y Rollback completo")
        print("5. Salir")
        opc = input("\nSeleccione una opción (1-5): ").strip()

        if opc == "1":
            demo_camino_feliz()
        elif opc == "2":
            demo_concurrencia_doble_entrega()
        elif opc == "3":
            demo_falla_cassandra_y_rollback()
        elif opc == "4":
            demo_falla_mongo_y_rollback()
        elif opc == "5":
            print("Saliendo...")
            break
        else:
            print("Opción inválida.")


if __name__ == "__main__":
    menu()
