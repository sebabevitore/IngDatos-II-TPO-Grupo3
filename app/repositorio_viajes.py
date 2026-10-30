from datetime import datetime, timezone
from uuid import uuid4


def registrar_viaje(coleccion, datos, id_operacion=None, id_viaje=None):
    """
    Registra un viaje en MongoDB.

    El parametro coleccion permite utilizar
    MongoDB real o una coleccion simulada.
    Permite recibir un id_viaje pregenerado para compartirlo
    con Neo4j garantizando el identificador común.
    """

    id_viaje = id_viaje or str(uuid4())

    documento = {
        "_id": id_viaje,
        "id_operacion": id_operacion or str(uuid4()),
        "id_ruta": datos["id_ruta"],
        "id_vehiculo": datos["id_vehiculo"],
        "id_conductor": datos["id_conductor"],
        "paquetes": datos["paquetes"].copy(),
        "estado": "PLANIFICADO",
        "fecha_creacion": datetime.now(timezone.utc)
    }

    coleccion.insert_one(documento)

    return id_viaje


def eliminar_viaje(coleccion, id_viaje):
    """
    Compensacion: elimina un viaje registrado.
    Solo debe usarse cuando la operacion
    aun no se confirmo.
    """
    resultado = coleccion.delete_one({"_id": id_viaje})
    return resultado.deleted_count == 1
