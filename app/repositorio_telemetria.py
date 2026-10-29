
from datetime import datetime, timezone
from uuid import UUID


def registrar_medicion_cassandra(sesion, datos):
    """
    Guarda una medición GPS en el historial de Cassandra.

    Escribe en la tabla por vehículo y día.
    Si existe viaje_id, también escribe en la tabla por viaje y día.

    Los INSERT de Cassandra son idempotentes respecto de la misma
    clave primaria: repetirlos con los mismos datos no crea otra fila.
    """

    # 1. Interpretar la fecha recibida.
    fecha_hora = datetime.fromisoformat(
        str(datos["fecha_hora"]).replace("Z", "+00:00")
    )

    # 2. Normalizar a UTC.
    if fecha_hora.tzinfo is None:
        raise ValueError(
            "fecha_hora debe incluir zona horaria"
        )

    fecha_hora_utc = fecha_hora.astimezone(timezone.utc)
    dia = fecha_hora_utc.date()

    # Cassandra recibe un datetime sin tzinfo, interpretado como UTC.
    fecha_hora_utc = fecha_hora_utc.replace(tzinfo=None)

    id_evento = UUID(str(datos["id_evento"]))
    patente = datos["vehiculo_patente"].strip()
    viaje_id = datos.get("viaje_id")

    # 3. Guardar el historial por vehículo y día.
    sesion.execute(
        """
        INSERT INTO logistica_flota.telemetria_por_vehiculo_dia
        (vehiculo_patente, dia, fecha_hora, id_evento, viaje_id,
         latitud, longitud, velocidad, estado_vehiculo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            patente,
            dia,
            fecha_hora_utc,
            id_evento,
            viaje_id,
            float(datos["latitud"]),
            float(datos["longitud"]),
            float(datos["velocidad"]),
            datos["estado_vehiculo"],
        ),
    )

    # 4. Guardar también el historial por viaje, si corresponde.
    if viaje_id:
        sesion.execute(
            """
            INSERT INTO logistica_flota.telemetria_por_viaje_dia
            (viaje_id, dia, fecha_hora, id_evento, vehiculo_patente,
             latitud, longitud, velocidad, estado_vehiculo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                viaje_id,
                dia,
                fecha_hora_utc,
                id_evento,
                patente,
                float(datos["latitud"]),
                float(datos["longitud"]),
                float(datos["velocidad"]),
                datos["estado_vehiculo"],
            ),
        )

    return {
        "id_evento": str(id_evento),
        "vehiculo_patente": patente,
        "viaje_id": viaje_id,
        "dia": str(dia),
        "historial_vehiculo_guardado": True,
        "historial_viaje_guardado": bool(viaje_id),
    }
