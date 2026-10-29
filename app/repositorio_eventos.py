
from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError



def registrar_evento(coleccion, id_evento, datos):
    """
    Registra un evento GPS si todavía no existe.

    Devuelve:
        (documento, True) si se creó.
        (documento, False) si ya existía con los mismos datos.

    Si el mismo ID se reutiliza con datos diferentes, genera un error.
    """
    existente = coleccion.find_one({"_id": id_evento})

    if existente is not None:
        if existente.get("datos") != datos:
            raise ValueError(
                "El id_evento ya existe con datos diferentes"
            )

        return existente, False

    ahora = datetime.now(timezone.utc)

    documento = {
        "_id": id_evento,
        "datos": datos.copy(),
        "estado_procesamiento": "PENDIENTE",
        "cassandra_guardado": False,
        "redis_procesado": False,
        "creado_en": ahora,
        "actualizado_en": ahora,
        "error": None,
    }

    try:
        coleccion.insert_one(documento)
        return documento, True

    except DuplicateKeyError:
        # Otro proceso pudo registrar el mismo evento al mismo tiempo.
        existente = coleccion.find_one({"_id": id_evento})

        if existente is None:
            raise

        if existente.get("datos") != datos:
            raise ValueError(
                "El id_evento ya existe con datos diferentes"
            )

        return existente, False




def obtener_evento(coleccion, id_evento):
    """Obtiene un evento por su identificador."""
    return coleccion.find_one({"_id": id_evento})


def actualizar_evento(coleccion, id_evento, **cambios):
    """Actualiza el progreso de un evento existente."""

    cambios["actualizado_en"] = datetime.now(timezone.utc)

    resultado = coleccion.update_one(
        {"_id": id_evento},
        {"$set": cambios}
    )

    return resultado.matched_count == 1
