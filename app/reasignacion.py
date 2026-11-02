"""Rescate durable; preserva historial y compensa también la consolidación final."""

from contextlib import ExitStack
from app.conexiones import conectar_mongodb, conectar_redis, conectar_neo4j
from app.flujos_durables import reasignar


def reasignar_por_averia(datos_averia, inyector=None):
    try:
        with ExitStack() as stack:
            mongo = conectar_mongodb()
            stack.callback(mongo.close)
            redis = conectar_redis()
            stack.callback(redis.close)
            neo = conectar_neo4j()
            stack.callback(neo.close)
            return reasignar(
                redis, mongo["logistica_flota"], neo, dict(datos_averia), inyector
            )
    except Exception as exc:
        return dict(exito=False, error=str(exc), compensado=False)
