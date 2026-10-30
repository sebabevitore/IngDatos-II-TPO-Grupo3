"""
Orquestador Saga para el Caso de Uso 5: Reasignación por avería (MongoDB + Redis + Neo4j).
Implementa el flujo transaccional distribuido con compensaciones automáticas (Rollback)
y garantía estricta de que ningún paquete quede sin asignación o con dos asignaciones activas.
"""

from uuid import uuid4
from typing import Dict, Any, Optional, List

from app.conexiones import conectar_mongodb, conectar_redis, conectar_neo4j
from app.fallas import InyectorFallas, FallaSimuladaError
from app.repositorio_reasignacion_redis import (
    reservar_reemplazo_redis,
    compensar_reserva_redis,
    consolidar_estados_redis,
)
from app.repositorio_reasignacion_neo4j import (
    vincular_rescate_neo4j,
    compensar_rescate_neo4j,
)
from app.repositorio_reasignacion_mongo import (
    ejecutar_reasignacion_mongo,
    compensar_reasignacion_mongo,
)


def reasignar_por_averia(
    datos_averia: Dict[str, Any],
    inyector: Optional[InyectorFallas] = None
) -> Dict[str, Any]:
    """
    Ejecuta el proceso Saga de reasignación por avería mecánica:
    
      Paso 1: [Redis] Reserva atómica del vehículo y chofer de reemplazo.
      Paso 2: [Neo4j] Validación vial y vinculación del recorrido de rescate en el grafo.
      Paso 3: [MongoDB] Cierre de asignaciones anteriores y creación de las nuevas (sin huérfanos ni duplicados).
      Paso 4: [Redis] Consolidación de estados operativos definitivos (AVERIADO / EN_VIAJE).
      
    Si cualquier paso falla, se disparan las compensaciones inversas exactas.
    """
    id_viaje_averiado = datos_averia["id_viaje_averiado"]
    patente_averiada = datos_averia["patente_averiada"]
    patente_reemplazo = datos_averia["patente_reemplazo"]
    conductor_reemplazo = datos_averia["conductor_reemplazo"]
    id_punto_averia = datos_averia.get("id_punto_averia", "PUNTO-CENTRO")
    puntos_destino = datos_averia.get("puntos_destino", ["PUNTO-NORTE"])

    saga_id = f"SAGA-AV-{uuid4().hex[:8]}"
    id_viaje_rescate = f"VIAJE-RESCATE-{uuid4().hex[:6]}"

    cliente_mongo = None
    cliente_redis = None
    driver_neo4j = None

    pasos_completados: List[str] = []

    try:
        cliente_mongo = conectar_mongodb()
        cliente_redis = conectar_redis()
        driver_neo4j = conectar_neo4j()

        # =====================================================================
        # PASO 1: [Redis] Reserva atómica de recursos de reemplazo
        # =====================================================================
        if inyector:
            inyector.verificar("CU05_REDIS_RESERVA")

        exito_reserva, motivo_reserva = reservar_reemplazo_redis(
            cliente_redis,
            patente_reemplazo=patente_reemplazo,
            conductor_reemplazo=conductor_reemplazo,
            token_saga=saga_id
        )

        if not exito_reserva:
            return {
                "exito": False,
                "saga_id": saga_id,
                "paso_fallido": "REDIS_RESERVA",
                "error": motivo_reserva,
                "compensado": False,
                "detalle": "La reserva no pudo realizarse; no hubo cambios en ningún motor."
            }

        pasos_completados.append("REDIS_RESERVA")

        # =====================================================================
        # PASO 2: [Neo4j] Vinculación del viaje de rescate en la red logística
        # =====================================================================
        try:
            if inyector:
                inyector.verificar("CU05_NEO4J")

            res_neo4j = vincular_rescate_neo4j(
                driver_neo4j,
                id_viaje_averiado=id_viaje_averiado,
                id_viaje_rescate=id_viaje_rescate,
                id_punto_averia=id_punto_averia,
                puntos_destino=puntos_destino
            )
            pasos_completados.append("NEO4J_VINCULACION")

        except Exception as err_neo4j:
            # ROLLBACK PASO 2: Liberar la reserva en Redis
            compensar_reserva_redis(
                cliente_redis, patente_reemplazo, conductor_reemplazo, saga_id
            )
            return {
                "exito": False,
                "saga_id": saga_id,
                "paso_fallido": "NEO4J",
                "error": str(err_neo4j),
                "compensaciones": ["REDIS_RESERVA_LIBERADA"],
                "detalle": "Fallo en Neo4j. Se liberó la reserva en Redis; ningún dato persistió en disco."
            }

        # =====================================================================
        # PASO 3: [MongoDB] Cierre de asignaciones y nuevo contrato de negocio
        # =====================================================================
        try:
            if inyector:
                inyector.verificar("CU05_MONGO")

            res_mongo = ejecutar_reasignacion_mongo(
                cliente_mongo,
                id_viaje_averiado=id_viaje_averiado,
                id_viaje_rescate=id_viaje_rescate,
                patente_reemplazo=patente_reemplazo,
                conductor_reemplazo=conductor_reemplazo,
                id_punto_averia=id_punto_averia,
                saga_id=saga_id
            )
            pasos_completados.append("MONGO_REASIGNACION")

        except Exception as err_mongo:
            # ROLLBACK PASO 3: Compensar Neo4j y luego Redis en orden inverso
            compensar_rescate_neo4j(driver_neo4j, id_viaje_rescate, id_viaje_averiado)
            compensar_reserva_redis(cliente_redis, patente_reemplazo, conductor_reemplazo, saga_id)
            compensar_reasignacion_mongo(cliente_mongo, id_viaje_averiado, id_viaje_rescate, saga_id)

            return {
                "exito": False,
                "saga_id": saga_id,
                "paso_fallido": "MONGODB",
                "error": str(err_mongo),
                "compensaciones": [
                    "MONGO_REVERTIDO",
                    "NEO4J_DESVINCULADO",
                    "REDIS_RESERVA_LIBERADA"
                ],
                "detalle": "Fallo en MongoDB. Se revirtió el grafo en Neo4j y se liberó el camión en Redis. Paquetes seguros."
            }

        # =====================================================================
        # PASO 4: [Redis] Consolidación de estados operativos
        # =====================================================================
        try:
            if inyector:
                inyector.verificar("CU05_REDIS_CONFIRM")

            consolidar_estados_redis(
                cliente_redis,
                patente_averiada=patente_averiada,
                patente_reemplazo=patente_reemplazo,
                id_viaje_rescate=id_viaje_rescate,
                token_saga=saga_id
            )
            pasos_completados.append("REDIS_CONSOLIDACION")

        except Exception as err_redis_final:
            # En este punto el negocio ya es consistente en MongoDB y Neo4j
            return {
                "exito": True,
                "saga_id": saga_id,
                "alerta": f"Reasignación confirmada pero falló consolidación en Redis: {err_redis_final}",
                "id_viaje_rescate": id_viaje_rescate
            }

        return {
            "exito": True,
            "saga_id": saga_id,
            "id_viaje_averiado": id_viaje_averiado,
            "id_viaje_rescate": id_viaje_rescate,
            "patente_averiada": patente_averiada,
            "patente_reemplazo": patente_reemplazo,
            "conductor_reemplazo": conductor_reemplazo,
            "total_paquetes": res_mongo["total_paquetes"],
            "paquetes_reasignados": res_mongo["paquetes_reasignados"],
            "pasos_completados": pasos_completados
        }

    finally:
        if cliente_redis is not None:
            try:
                cliente_redis.close()
            except Exception:
                pass
        if cliente_mongo is not None:
            try:
                cliente_mongo.close()
            except Exception:
                pass
        if driver_neo4j is not None:
            try:
                driver_neo4j.close()
            except Exception:
                pass

