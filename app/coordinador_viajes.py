"""Planificación persistente con compensación recuperable e identidad de solicitud."""

from app.viajes import validar_viaje
from app.flujos_durables import planificar


def planificar_viaje(
    cliente_redis, coleccion_mongo, datos, driver_neo4j=None, inyector=None
):
    valido, mensaje = validar_viaje(datos)
    if not valido:
        return False, mensaje
    if driver_neo4j is None:
        return False, "CU01 requiere Neo4j"
    if coleccion_mongo.database.name != "logistica_flota":
        return False, "Base de negocio incorrecta"
    try:
        resultado = planificar(
            cliente_redis, coleccion_mongo.database, dict(datos), driver_neo4j, inyector
        )
        return resultado.get("exito", False), resultado
    except Exception as exc:
        return False, dict(error=str(exc), compensado=False)
