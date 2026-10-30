"""
Menú interactivo de prueba para el Caso de Uso 5: Reasignación por avería (MongoDB + Redis + Neo4j).
Permite ejecutar y verificar todos los escenarios exigidos por la consigna (Sección 4, 5 y 8).
"""

import os
import sys

# Permite ejecutar directamente el archivo con el botón de Play del editor
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from app.conexiones import conectar_mongodb, conectar_redis, conectar_neo4j
from app.fallas import InyectorFallas
from app.reasignacion import reasignar_por_averia
from app.repositorio_reasignacion_mongo import asegurar_viaje_prueba_mongo


def preparar_escenario_base(
    id_viaje="VIAJE-101",
    patente_averiada="AA111AA",
    conductor_averiado="COND-01",
    paquetes=None
):
    """Inicializa datos limpios en MongoDB para poder ejecutar la prueba."""
    if paquetes is None:
        paquetes = ["PAQ-1001", "PAQ-1002"]

    mongo = conectar_mongodb()
    try:
        asegurar_viaje_prueba_mongo(
            mongo,
            id_viaje=id_viaje,
            patente=patente_averiada,
            conductor=conductor_averiado,
            paquetes=paquetes
        )
    finally:
        mongo.close()


def demo_camino_feliz():
    print("\n--- 1. ESCENARIO: Camino feliz - Reasignación completa por avería ---")
    id_viaje = "VIAJE-FELIZ-01"
    patente_averiada = "AA111AA"
    patente_reemplazo = "AF999ZZ"
    conductor_reemplazo = "COND-RESCATE-01"
    paquetes = ["PAQ-901", "PAQ-902"]

    print(f"Preparando viaje original {id_viaje} con vehículo {patente_averiada} y paquetes {paquetes}...")
    preparar_escenario_base(id_viaje, patente_averiada, "COND-ORIG-01", paquetes)

    datos = {
        "id_viaje_averiado": id_viaje,
        "patente_averiada": patente_averiada,
        "patente_reemplazo": patente_reemplazo,
        "conductor_reemplazo": conductor_reemplazo,
        "id_punto_averia": "PUNTO-CENTRO",
        "puntos_destino": ["PUNTO-NORTE"]
    }

    print("\nEjecutando reasignación (Redis -> Neo4j -> MongoDB -> Redis)...")
    res = reasignar_por_averia(datos)
    print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))

    # Verificación en Redis
    redis_cli = conectar_redis()
    estado_averiado = redis_cli.hgetall(f"vehiculo:{patente_averiada}:estado")
    estado_reemplazo = redis_cli.hgetall(f"vehiculo:{patente_reemplazo}:estado")
    redis_cli.close()

    print("\n[VERIFICACIÓN EN REDIS]")
    print(f"  Vehículo averiado ({patente_averiada}):", estado_averiado)
    print(f"  Vehículo reemplazo ({patente_reemplazo}):", estado_reemplazo)


def demo_concurrencia():
    print("\n--- 2. ESCENARIO: Concurrencia - Dos coordinadores intentan usar el mismo camión ---")
    patente_disputada = "AD777XX"
    conductor = "COND-UNICO-01"

    # Preparar dos viajes averiados distintos
    preparar_escenario_base("VIAJE-CONC-A", "AA100AA", "COND-A", ["PAQ-A1"])
    preparar_escenario_base("VIAJE-CONC-B", "BB200BB", "COND-B", ["PAQ-B1"])

    datos_op1 = {
        "id_viaje_averiado": "VIAJE-CONC-A",
        "patente_averiada": "AA100AA",
        "patente_reemplazo": patente_disputada,
        "conductor_reemplazo": conductor,
        "id_punto_averia": "PUNTO-CENTRO",
        "puntos_destino": ["PUNTO-NORTE"]
    }

    datos_op2 = {
        "id_viaje_averiado": "VIAJE-CONC-B",
        "patente_averiada": "BB200BB",
        "patente_reemplazo": patente_disputada,
        "conductor_reemplazo": conductor,
        "id_punto_averia": "PUNTO-CENTRO",
        "puntos_destino": ["PUNTO-OESTE"]
    }

    print(f"Disparando 2 solicitudes en simultáneo para competir por el vehículo {patente_disputada}...")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro1 = executor.submit(reasignar_por_averia, datos_op1)
        futuro2 = executor.submit(reasignar_por_averia, datos_op2)

        res1 = futuro1.result()
        res2 = futuro2.result()

    print("\n[RESPUESTA OPERADOR 1]:")
    print(json.dumps(res1, indent=2, ensure_ascii=False))
    print("\n[RESPUESTA OPERADOR 2]:")
    print(json.dumps(res2, indent=2, ensure_ascii=False))

    exitos = sum([1 for r in [res1, res2] if r["exito"]])
    print(f"\n[CONTROL DE CONCURRENCIA]: Ganador único = {'SÍ' if exitos == 1 else 'NO (ERROR)'}")


def demo_falla_neo4j_y_rollback():
    print("\n--- 3. ESCENARIO: Falla inducida en Neo4j -> Rollback automático en Redis ---")
    id_viaje = "VIAJE-FALLA-N4J"
    patente_averiada = "AC333CC"
    patente_reemplazo = "AG555YY"
    conductor = "COND-N4J"

    preparar_escenario_base(id_viaje, patente_averiada, "COND-ORIG", ["PAQ-N4J-1"])

    datos = {
        "id_viaje_averiado": id_viaje,
        "patente_averiada": patente_averiada,
        "patente_reemplazo": patente_reemplazo,
        "conductor_reemplazo": conductor,
        "id_punto_averia": "PUNTO-CENTRO",
        "puntos_destino": ["PUNTO-NORTE"]
    }

    inyector = InyectorFallas("CU05_NEO4J")
    print("Ejecutando con fallo forzado en el paso 'CU05_NEO4J'...")
    res = reasignar_por_averia(datos, inyector=inyector)
    print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))

    # Comprobar que la reserva en Redis fue liberada
    redis_cli = conectar_redis()
    lock_existe = redis_cli.exists(f"reserva:vehiculo:{patente_reemplazo}")
    redis_cli.close()
    print(f"Comprobación de Rollback: ¿El lock del camión {patente_reemplazo} fue liberado? {'SÍ (ROLLBACK EXITOSO)' if not lock_existe else 'NO (QUEDÓ BLOQUEADO)'}")


def demo_falla_mongo_y_rollback():
    print("\n--- 4. ESCENARIO: Falla inducida en MongoDB -> Rollback en Neo4j y Redis ---")
    id_viaje = "VIAJE-FALLA-MONGO"
    patente_averiada = "AD444DD"
    patente_reemplazo = "AH666ZZ"
    conductor = "COND-MONGO"

    preparar_escenario_base(id_viaje, patente_averiada, "COND-ORIG", ["PAQ-M1", "PAQ-M2"])

    datos = {
        "id_viaje_averiado": id_viaje,
        "patente_averiada": patente_averiada,
        "patente_reemplazo": patente_reemplazo,
        "conductor_reemplazo": conductor,
        "id_punto_averia": "PUNTO-CENTRO",
        "puntos_destino": ["PUNTO-NORTE"]
    }

    inyector = InyectorFallas("CU05_MONGO")
    print("Ejecutando con fallo forzado en el paso 'CU05_MONGO'...")
    res = reasignar_por_averia(datos, inyector=inyector)
    print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))

    # Comprobar que en MongoDB las asignaciones originales siguen activas
    mongo = conectar_mongodb()
    asignaciones_activas = list(mongo["logistica_flota"].asignaciones.find({
        "viaje_id": id_viaje,
        "estado": "ACTIVA"
    }))
    mongo.close()

    print(f"\n[COMPROBACIÓN EN MONGODB]:")
    print(f"  Asignaciones activas que siguen en el viaje original: {len(asignaciones_activas)}")
    print(f"  ¿Los paquetes quedaron a salvo sin asignaciones huérfanas? {'SÍ (ROLLBACK EXITOSO)' if len(asignaciones_activas) == 2 else 'NO'}")


def menu():
    while True:
        print("\n=============================================================")
        print("   TPO - CU-05: Reasignación por avería (MongoDB + Redis + Neo4j)")
        print("=============================================================")
        print("1. Camino feliz: Reasignación completa exitosa")
        print("2. Concurrencia: Dos coordinadores disputan el mismo vehículo")
        print("3. Demostración de Falla: Error en Neo4j y Rollback en Redis")
        print("4. Demostración de Falla: Error en MongoDB y Rollback completo")
        print("5. Salir")
        opc = input("\nSeleccione una opción (1-5): ").strip()

        if opc == "1":
            demo_camino_feliz()
        elif opc == "2":
            demo_concurrencia()
        elif opc == "3":
            demo_falla_neo4j_y_rollback()
        elif opc == "4":
            demo_falla_mongo_y_rollback()
        elif opc == "5":
            print("Saliendo...")
            break
        else:
            print("Opción inválida.")


if __name__ == "__main__":
    menu()
