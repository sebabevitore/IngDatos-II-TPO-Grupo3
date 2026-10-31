
from datetime import date


def consultar_telemetria_viaje(sesion, viaje_id, dia):
    """
    Consulta las posiciones GPS de un viaje durante un día.
    Usa la clave de partición (viaje_id, dia).
    """

    consulta = """
        SELECT viaje_id, fecha_hora, id_evento,
               vehiculo_patente, latitud, longitud,
               velocidad, estado_vehiculo
        FROM logistica_flota.telemetria_por_viaje_dia
        WHERE viaje_id = %s AND dia = %s
    """

    filas = sesion.execute(consulta, (viaje_id, dia))

    return [
        {
            "viaje_id": fila.viaje_id,
            "fecha_hora": fila.fecha_hora.isoformat(),
            "id_evento": str(fila.id_evento),
            "vehiculo": fila.vehiculo_patente,
            "latitud": fila.latitud,
            "longitud": fila.longitud,
            "velocidad": fila.velocidad,
            "estado": fila.estado_vehiculo
        }
        for fila in filas
    ]


def consultar_alertas_viaje(sesion, viaje_id, dia):
    """
    Consulta las alertas históricas de un viaje durante un día.
    """

    consulta = """
        SELECT viaje_id, fecha_hora, alerta_id,
               vehiculo_patente, tipo, descripcion,
               latitud, longitud, resuelta
        FROM logistica_flota.alertas_por_viaje_dia
        WHERE viaje_id = %s AND dia = %s
    """

    filas = sesion.execute(consulta, (viaje_id, dia))

    return [
        {
            "viaje_id": fila.viaje_id,
            "fecha_hora": fila.fecha_hora.isoformat(),
            "alerta_id": fila.alerta_id,
            "vehiculo": fila.vehiculo_patente,
            "tipo": fila.tipo,
            "descripcion": fila.descripcion,
            "latitud": fila.latitud,
            "longitud": fila.longitud,
            "resuelta": fila.resuelta
        }
        for fila in filas
    ]
