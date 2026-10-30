"""
Módulo de Reconciliación para el Caso de Uso 3 (Cassandra + Redis).

Responsabilidad:
  Garantiza la consistencia eventual entre Cassandra y Redis ante fallos parciales
  o reinicios de Redis, respetando el principio fundamental de diseño:
  "Cassandra es la fuente duradera de la verdad; Redis es el estado efímero".
"""

import os
from typing import Dict, Any, List
from app.conexiones import conectar_cassandra, conectar_redis
from app.repositorio_alertas import obtener_alertas_abiertas_cassandra
from app.repositorio_alertas_redis import (
    clave_alerta_activa,
    confirmar_anomalia_redis,
)


def reconciliar_anomalias() -> Dict[str, Any]:
    """
    Ejecuta el proceso de reconciliación entre Cassandra y Redis.

    Acciones que realiza:
      1. Lee todas las alertas abiertas desde Cassandra (alertas_abiertas_por_vehiculo).
      2. Para cada una, verifica su presencia en Redis:
         - Si no existe (Redis se reinició, se ejecutó FLUSHALL, o falló el Paso 3),
           recrea la clave en Redis con estado ACTIVE y el TTL configurado.
         - Si estaba en estado PENDING, la promueve a ACTIVE.
      3. Inspecciona claves en Redis en estado PENDING que hayan quedado huérfanas
         por una caída del proceso antes de escribir en Cassandra, y las limpia.
    """
    cluster = None
    cliente_redis = None

    reconstruidas_en_redis = []
    confirmadas_en_redis = []
    huerfanas_limpiadas = []

    ttl_activo = int(os.getenv("REDIS_ANOMALIA_TTL_SEGUNDOS", "120"))

    try:
        cluster, sesion = conectar_cassandra()
        cliente_redis = conectar_redis()

        # 1. Cassandra -> Redis: Asegurar que toda alerta abierta en Cassandra exista en Redis
        alertas_abiertas = obtener_alertas_abiertas_cassandra(sesion)

        for abierta in alertas_abiertas:
            patente = abierta["vehiculo_patente"]
            tipo = abierta["tipo"]
            alerta_id = abierta["alerta_id"]
            viaje_id = abierta.get("viaje_id") or ""
            dia = abierta["dia"]
            fecha_hora = abierta["fecha_hora"]

            clave = clave_alerta_activa(patente, tipo)
            datos_redis = cliente_redis.hgetall(clave)

            if not datos_redis:
                # Caso: Redis perdió la clave (reinicio / flush / fallo paso 3).
                # Reconstruimos la clave en Redis desde la fuente de verdad.
                pipe = cliente_redis.pipeline()
                pipe.hset(clave, mapping={
                    "alerta_id": alerta_id,
                    "estado": "ACTIVE",
                    "viaje_id": viaje_id,
                    "dia": dia,
                    "fecha_hora": fecha_hora or "",
                    "primera_vez": fecha_hora or "",
                    "ultima_vez": fecha_hora or "",
                    "cantidad": "1"
                })
                pipe.expire(clave, ttl_activo)
                pipe.execute()

                reconstruidas_en_redis.append({
                    "patente": patente,
                    "tipo": tipo,
                    "alerta_id": alerta_id,
                    "motivo": "Clave ausente en Redis; restaurada desde Cassandra"
                })

            elif datos_redis.get("estado") == "PENDING" and datos_redis.get("alerta_id") == alerta_id:
                # Caso: Quedó en PENDING porque el paso 3 falló, pero Cassandra SÍ lo persistió.
                # Promovemos a ACTIVE.
                confirmar_anomalia_redis(cliente_redis, patente, tipo, alerta_id, ttl_activo=ttl_activo)
                confirmadas_en_redis.append({
                    "patente": patente,
                    "tipo": tipo,
                    "alerta_id": alerta_id,
                    "motivo": "Promovida de PENDING a ACTIVE en Redis"
                })

        # 2. Redis -> Cassandra: Buscar claves PENDING en Redis que NO existan en Cassandra (huérfanas)
        patron = "alerta:activa:*"
        for clave in cliente_redis.scan_iter(patron):
            estado = cliente_redis.hget(clave, "estado")
            if estado == "PENDING":
                alerta_id_redis = cliente_redis.hget(clave, "alerta_id")
                # Verificar si existe en la lista de alertas abiertas de Cassandra
                existe_en_cassandra = any(a["alerta_id"] == alerta_id_redis for a in alertas_abiertas)

                if not existe_en_cassandra:
                    # Es una clave huérfana de un proceso interrumpido antes del paso 2.
                    cliente_redis.delete(clave)
                    huerfanas_limpiadas.append({
                        "clave": clave,
                        "alerta_id": alerta_id_redis,
                        "motivo": "Claim PENDING sin persistencia en Cassandra eliminado"
                    })

        return {
            "exito": True,
            "total_alertas_abiertas_cassandra": len(alertas_abiertas),
            "reconstruidas_en_redis": reconstruidas_en_redis,
            "confirmadas_en_redis": confirmadas_en_redis,
            "huerfanas_limpiadas": huerfanas_limpiadas
        }

    finally:
        if cluster is not None:
            try:
                cluster.shutdown()
            except Exception:
                pass
        if cliente_redis is not None:
            try:
                cliente_redis.close()
            except Exception:
                pass

