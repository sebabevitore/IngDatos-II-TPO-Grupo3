
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.conexiones import (
    conectar_mongodb,
    conectar_cassandra,
    conectar_neo4j,
)
from app.trazabilidad import consultar_trazabilidad_completa


def preparar_datos_prueba_cu08():
    """Siembra de forma idempotente los datos requeridos por las pruebas del CU-08."""
    # 1. MongoDB
    cliente_mongo = conectar_mongodb()
    try:
        db = cliente_mongo["logistica_flota"]
        ahora = datetime.now(timezone.utc)
        inicio_v1 = ahora - timedelta(hours=3)
        fin_v1 = ahora - timedelta(hours=1)
        inicio_v2 = ahora - timedelta(hours=1)

        db.paquetes.replace_one(
            {"_id": "PAQ-CU08-001"},
            {
                "_id": "PAQ-CU08-001",
                "codigo_seguimiento": "PAQ-CU08-001",
                "estado": "EN_TRANSITO",
                "fecha_registro": ahora - timedelta(days=1),
                "peso": 3.5,
            },
            upsert=True
        )

        db.asignaciones.delete_many({"paquete_codigo": "PAQ-CU08-001"})
        db.asignaciones.insert_many([
            {
                "paquete_codigo": "PAQ-CU08-001",
                "viaje_id": "VIAJE-CU08-001",
                "estado": "INTERRUMPIDA",
                "fecha_asignacion": inicio_v1,
                "fecha_fin": fin_v1,
                "punto_inicio_id": "PTO-CU08-1",
                "punto_fin_id": "PTO-CU08-2",
            },
            {
                "paquete_codigo": "PAQ-CU08-001",
                "viaje_id": "VIAJE-CU08-002",
                "estado": "ACTIVA",
                "fecha_asignacion": inicio_v2,
                "fecha_fin": None,
                "punto_inicio_id": "PTO-CU08-2",
                "punto_fin_id": "PTO-CU08-3",
            }
        ])

        db.viajes.replace_one(
            {"_id": "VIAJE-CU08-001"},
            {
                "_id": "VIAJE-CU08-001",
                "vehiculo_patente": "AB123CD",
                "conductor_id": "COND-CU08-1",
                "ruta_id": "RUTA-CU08-001",
                "estado": "INTERRUMPIDO",
            },
            upsert=True
        )

        db.viajes.replace_one(
            {"_id": "VIAJE-CU08-002"},
            {
                "_id": "VIAJE-CU08-002",
                "vehiculo_patente": "AC456EF",
                "conductor_id": "COND-CU08-2",
                "ruta_id": "RUTA-CU08-002",
                "estado": "EN_CURSO",
            },
            upsert=True
        )
    finally:
        cliente_mongo.close()

    # 2. Cassandra
    cluster, sesion = conectar_cassandra()
    try:
        dia_v1 = inicio_v1.date()
        dia_v2 = inicio_v2.date()

        # Telemetría Viaje 1
        cql_telemetria = """
            INSERT INTO logistica_flota.telemetria_por_viaje_dia
            (viaje_id, dia, fecha_hora, id_evento, vehiculo_patente, latitud, longitud, velocidad, estado_vehiculo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        sesion.execute(
            cql_telemetria,
            (
                "VIAJE-CU08-001", dia_v1, inicio_v1 + timedelta(minutes=20),
                uuid4(), "AB123CD", -34.601, -58.401, 50.0, "EN_MOVIMIENTO"
            )
        )

        # Telemetría Viaje 2
        sesion.execute(
            cql_telemetria,
            (
                "VIAJE-CU08-002", dia_v2, inicio_v2 + timedelta(minutes=20),
                uuid4(), "AC456EF", -34.611, -58.411, 45.0, "EN_MOVIMIENTO"
            )
        )

        # Alerta Viaje 1
        cql_alerta = """
            INSERT INTO logistica_flota.alertas_por_viaje_dia
            (viaje_id, dia, fecha_hora, alerta_id, vehiculo_patente, tipo, descripcion, latitud, longitud, resuelta)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        sesion.execute(
            cql_alerta,
            (
                "VIAJE-CU08-001", dia_v1, inicio_v1 + timedelta(minutes=30),
                f"ALT-{uuid4().hex[:6]}", "AB123CD", "AVERIA_MECANICA",
                "Falla en motor", -34.605, -58.405, True
            )
        )
    finally:
        cluster.shutdown()

    # 3. Neo4j
    driver = conectar_neo4j()
    try:
        cypher = """
        MERGE (p1:PuntoEntrega {punto_entrega_id: 'PTO-CU08-1'})
          ON CREATE SET p1.nombre = 'Depósito Origen', p1.latitud = -34.60, p1.longitud = -58.40
        MERGE (p2:PuntoEntrega {punto_entrega_id: 'PTO-CU08-2'})
          ON CREATE SET p2.nombre = 'Nodo Transbordo', p2.latitud = -34.61, p2.longitud = -58.41
        MERGE (p3:PuntoEntrega {punto_entrega_id: 'PTO-CU08-3'})
          ON CREATE SET p3.nombre = 'Punto Destino', p3.latitud = -34.62, p3.longitud = -58.42

        MERGE (r1:Ruta {ruta_id: 'RUTA-CU08-001'})
        MERGE (r1)-[:INCLUYE {orden: 1}]->(p1)
        MERGE (r1)-[:INCLUYE {orden: 2}]->(p2)

        MERGE (r2:Ruta {ruta_id: 'RUTA-CU08-002'})
        MERGE (r2)-[:INCLUYE {orden: 1}]->(p2)
        MERGE (r2)-[:INCLUYE {orden: 2}]->(p3)

        MERGE (v1:Viaje {viaje_id: 'VIAJE-CU08-001'})
        MERGE (v1)-[:ASIGNADO_A]->(r1)

        MERGE (v2:Viaje {viaje_id: 'VIAJE-CU08-002'})
        MERGE (v2)-[:ASIGNADO_A]->(r2)
        """
        with driver.session() as sesion:
            sesion.run(cypher)
    finally:
        driver.close()


def main():
    preparar_datos_prueba_cu08()
    print("\n=== PRUEBAS INTEGRALES CU-08 ===")

    # Prueba 1: paquete existente con transferencia.
    resultado = consultar_trazabilidad_completa(
        "PAQ-CU08-001"
    )

    assert resultado["exito"] is True
    assert resultado["total_viajes"] == 2
    assert resultado["total_posiciones_gps"] >= 2
    assert resultado["total_alertas"] >= 1

    viajes = {
        viaje["viaje_id"]: viaje
        for viaje in resultado["viajes"]
    }

    original = viajes["VIAJE-CU08-001"]
    rescate = viajes["VIAJE-CU08-002"]

    assert original["vehiculo"] == "AB123CD"
    assert rescate["vehiculo"] == "AC456EF"

    assert original["estado_asignacion"] == "INTERRUMPIDA"
    assert rescate["estado_asignacion"] == "ACTIVA"

    assert len(original["recorrido"]) == 2
    assert len(rescate["recorrido"]) == 2

    assert original["total_posiciones"] >= 1
    assert rescate["total_posiciones"] >= 1
    assert original["total_alertas"] >= 1

    print("[OK] Paquete con transferencia")
    print("[OK] Vehiculos y asignaciones")
    print("[OK] Recorridos de Neo4j")
    print("[OK] GPS y alertas de Cassandra")

    # Prueba 2: paquete inexistente.
    inexistente = consultar_trazabilidad_completa(
        "PAQ-INEXISTENTE-999"
    )

    assert inexistente["exito"] is False
    assert "error" in inexistente

    print("[OK] Paquete inexistente")

    # Prueba 3: codigo vacio.
    try:
        consultar_trazabilidad_completa("   ")
    except ValueError:
        print("[OK] Codigo vacio rechazado")
    else:
        raise AssertionError(
            "El sistema deberia rechazar un codigo vacio"
        )

    print("\n[OK] TODAS LAS PRUEBAS CU-08 PASARON")


if __name__ == "__main__":
    main()
