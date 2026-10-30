"""
Orquestador Saga para el Caso de Uso 6: Confirmación de entrega (MongoDB + Cassandra + Redis).
Coordina la escritura distribuida con fallas y compensaciones, garantizando no repudio,
trazabilidad histórica y consistencia comercial.
"""

from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from app.conexiones import (
    conectar_mongodb,
    conectar_redis,
    conectar_cassandra
)
from app.fallas import InyectorFallas, FallaSimuladaError
from app.repositorio_entrega_redis import (
    bloquear_entrega_paquete_redis,
    liberar_bloqueo_entrega_redis,
    consolidar_entrega_redis
)
from app.repositorio_entrega_cassandra import (
    registrar_entrega_cassandra,
    compensar_entrega_cassandra
)
from app.repositorio_entrega_mongo import (
    actualizar_entrega_mongo,
    compensar_entrega_mongo
)


def confirmar_entrega_paquete(
    datos_entrega: Dict[str, Any],
    inyector: Optional[InyectorFallas] = None
) -> Dict[str, Any]:
    """
    Ejecuta el flujo Saga de confirmación de entrega:
      Paso 1: [Redis] Lock atómico temporal para evitar dobles confirmaciones concurrentes.
      Paso 2: [Cassandra] Inserción del evento inmutable de entrega (POD / Legal).
      Paso 3: [MongoDB] Actualización del documento del paquete a ENTREGADO y cierre de asignación.
      Paso 4: [Redis] Consolidación de contadores de viaje y liberación de lock.
      
    Si cualquier paso falla, se compensan en reversa los pasos previos.
    """
    paquete_codigo = str(datos_entrega["paquete_codigo"]).strip()
    viaje_id = str(datos_entrega["viaje_id"]).strip()

    if "fecha_hora" not in datos_entrega:
        datos_entrega["fecha_hora"] = datetime.now(timezone.utc).isoformat()

    saga_id = f"SAGA-ENTREGA-{uuid4().hex[:8]}"

    cliente_redis = None
    cliente_mongo = None
    cluster_cass = None

    pasos_completados: List[str] = []
    res_cassandra = None

    try:
        cliente_redis = conectar_redis()
        cliente_mongo = conectar_mongodb()
        cluster_cass, sesion_cass = conectar_cassandra()

        # =====================================================================
        # PASO 1: [Redis] Lock atómico de entrega (no duplicación)
        # =====================================================================
        if inyector:
            inyector.verificar("CU06_REDIS_LOCK")

        adquirido, motivo_lock = bloquear_entrega_paquete_redis(
            cliente_redis,
            paquete_codigo=paquete_codigo,
            token_saga=saga_id
        )

        if not adquirido:
            return {
                "exito": False,
                "saga_id": saga_id,
                "paso_fallido": "REDIS_LOCK",
                "error": motivo_lock,
                "compensado": False,
                "detalle": "La entrega ya fue realizada o está en proceso simultáneo."
            }

        pasos_completados.append("REDIS_LOCK")

        # =====================================================================
        # PASO 2: [Cassandra] Registro histórico legal inmutable (POD)
        # =====================================================================
        try:
            if inyector:
                inyector.verificar("CU06_CASSANDRA")

            res_cassandra = registrar_entrega_cassandra(sesion_cass, datos_entrega)
            pasos_completados.append("CASSANDRA_POD")

        except Exception as err_cass:
            # ROLLBACK PASO 2: Liberar lock en Redis
            liberar_bloqueo_entrega_redis(cliente_redis, paquete_codigo, saga_id)
            return {
                "exito": False,
                "saga_id": saga_id,
                "paso_fallido": "CASSANDRA",
                "error": str(err_cass),
                "compensaciones": ["REDIS_LOCK_LIBERADO"],
                "detalle": "Fallo al registrar evento legal en Cassandra. Lock de Redis liberado."
            }

        # =====================================================================
        # PASO 3: [MongoDB] Actualización de documentos comerciales
        # =====================================================================
        try:
            if inyector:
                inyector.verificar("CU06_MONGO")

            res_mongo = actualizar_entrega_mongo(cliente_mongo, datos_entrega, saga_id)
            pasos_completados.append("MONGO_CONTRATO")

        except Exception as err_mongo:
            # ROLLBACK PASO 3: Compensar Cassandra y luego Redis
            if res_cassandra:
                compensar_entrega_cassandra(
                    sesion_cass,
                    viaje_id=viaje_id,
                    dia=res_cassandra["dia"],
                    fecha_cql=res_cassandra["fecha_cql"],
                    paquete_codigo=paquete_codigo
                )
            liberar_bloqueo_entrega_redis(cliente_redis, paquete_codigo, saga_id)
            compensar_entrega_mongo(cliente_mongo, paquete_codigo, viaje_id, saga_id)

            return {
                "exito": False,
                "saga_id": saga_id,
                "paso_fallido": "MONGODB",
                "error": str(err_mongo),
                "compensaciones": [
                    "MONGO_REVERTIDO",
                    "CASSANDRA_POD_ELIMINADO",
                    "REDIS_LOCK_LIBERADO"
                ],
                "detalle": "Fallo en MongoDB. Se eliminó el evento de Cassandra y se liberó Redis. Paquete sigue EN_TRANSITO."
            }

        # =====================================================================
        # PASO 4: [Redis] Consolidación operativa y liberación de lock
        # =====================================================================
        try:
            if inyector:
                inyector.verificar("CU06_REDIS_CONFIRM")

            consolidar_entrega_redis(
                cliente_redis,
                viaje_id=viaje_id,
                paquete_codigo=paquete_codigo,
                token_saga=saga_id
            )
            pasos_completados.append("REDIS_CONSOLIDACION")

        except Exception as err_redis_final:
            return {
                "exito": True,
                "saga_id": saga_id,
                "alerta": f"Entrega persistida legalmente pero falló contador en Redis: {err_redis_final}",
                "paquete_codigo": paquete_codigo
            }

        return {
            "exito": True,
            "saga_id": saga_id,
            "viaje_id": viaje_id,
            "paquete_codigo": paquete_codigo,
            "receptor": datos_entrega.get("receptor_nombre", "Consignatario"),
            "id_evento_cassandra": res_cassandra["id_evento"] if res_cassandra else None,
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
        if cluster_cass is not None:
            try:
                cluster_cass.shutdown()
            except Exception:
                pass

