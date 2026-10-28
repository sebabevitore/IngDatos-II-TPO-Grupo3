from datetime import datetime, timezone
from uuid import UUID

def registrar_medicion_cassandra(sesion, datos):
    """
    Guarda una medición GPS en el historial de Cassandra.

    Escribe siempre en la tabla por vehículo y día.
    Si la medición tiene viaje_id, también escribe en la tabla por viaje y día.

    Recibe una sesión Cassandra y una medición previamente validada.
    """

    fecha_hora = datetime.fromisoformat(str(datos["fecha_hora"]).replace("Z", "+00:00"))

    fecha_hora_utc = fecha_hora.astimezone(timezone.utc)
    dia = fecha_hora_utc.date()
    fecha_hora_utc = fecha_hora_utc.replace(tzinfo=None)

    id_evento = UUID(str(datos["id_evento"]))
    patente = datos["vehiculo_patente"]
    viaje_id = datos.get("viaje_id")

    # Primera escritura: historial por vehículo y día.
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

    # Segunda escritura: historial por viaje y día, si corresponde.
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
