
from datetime import datetime, timezone


def normalizar_fecha(fecha):
    """Normaliza las fechas de MongoDB y Cassandra a UTC."""
    if fecha is None:
        return None

    if isinstance(fecha, str):
        fecha = datetime.fromisoformat(
            fecha.replace("Z", "+00:00")
        )

    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)

    return fecha.astimezone(timezone.utc)


def obtener_periodo_asignacion(asignacion):
    """Obtiene el inicio y fin del transporte del paquete."""
    inicio = normalizar_fecha(
        asignacion.get("fecha_asignacion")
    )

    fin = normalizar_fecha(
        asignacion.get("fecha_cierre")
        or asignacion.get("fecha_fin")
    )

    if inicio is None:
        raise ValueError(
            "La asignacion no tiene fecha de inicio"
        )

    if fin is not None and fin < inicio:
        raise ValueError(
            "La fecha de cierre es anterior al inicio"
        )

    return inicio, fin


def filtrar_eventos_por_periodo(eventos, inicio, fin):
    """
    Conserva únicamente los eventos ocurridos mientras
    el paquete estuvo asignado al viaje.

    Si la asignación está activa, el período queda abierto.
    """
    filtrados = []

    for evento in eventos:
        fecha_evento = normalizar_fecha(
            evento["fecha_hora"]
        )

        if fecha_evento < inicio:
            continue

        if fin is not None and fecha_evento >= fin:
            continue

        filtrados.append(evento)

    return filtrados
