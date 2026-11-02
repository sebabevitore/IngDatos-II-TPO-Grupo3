"""Confirmación de entrega durable; nunca confirma éxito con métricas pendientes."""

from contextlib import ExitStack
from app.conexiones import conectar_mongodb, conectar_redis, conectar_cassandra
from app.flujos_durables import entregar


def confirmar_entrega_paquete(datos_entrega, inyector=None):
    try:
        with ExitStack() as stack:
            mongo = conectar_mongodb()
            stack.callback(mongo.close)
            redis = conectar_redis()
            stack.callback(redis.close)
            cluster, cql = conectar_cassandra()
            stack.callback(cluster.shutdown)
            return entregar(
                redis, mongo["logistica_flota"], cql, dict(datos_entrega), inyector
            )
    except Exception as exc:
        return dict(exito=False, error=str(exc), compensado=False)
