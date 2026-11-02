"""Documentos de viaje con los identificadores que consumen todos los CU."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4


def registrar_viaje(coleccion, datos, id_operacion=None, id_viaje=None):
    ahora = datetime.now(timezone.utc)
    inicio = datos.get("inicio_planificado", ahora)
    viaje = id_viaje or str(uuid4())
    coleccion.insert_one(
        dict(
            _id=viaje,
            id_operacion=id_operacion or str(uuid4()),
            id_ruta=datos["id_ruta"],
            ruta_id=datos["id_ruta"],
            id_vehiculo=datos["id_vehiculo"],
            vehiculo_patente=datos["id_vehiculo"],
            id_conductor=datos["id_conductor"],
            conductor_id=datos["id_conductor"],
            paquetes=list(datos["paquetes"]),
            estado="PLANIFICADO",
            fecha_creacion=ahora,
            inicio_planificado=inicio,
            fin_planificado=datos.get("fin_planificado", inicio + timedelta(hours=2)),
            paradas=datos.get("paradas", []),
        )
    )
    return viaje


def eliminar_viaje(coleccion, id_viaje):
    return coleccion.delete_one({"_id": id_viaje}).deleted_count == 1
