"""Normalización UTC, horarios de paradas y disponibilidad por intervalos."""

from datetime import datetime, timedelta, timezone


def utc(valor):
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if not isinstance(valor, datetime):
        raise ValueError("Se esperaba fecha/hora ISO o datetime")
    # PyMongo devuelve UTC sin tzinfo por defecto.
    return (
        valor.replace(tzinfo=timezone.utc)
        if valor.tzinfo is None
        else valor.astimezone(timezone.utc)
    )


def intervalo(datos, ahora=None):
    inicio = utc(datos.get("inicio_planificado") or ahora or datetime.now(timezone.utc))
    fin = utc(datos.get("fin_planificado") or inicio + timedelta(hours=2))
    if fin <= inicio:
        raise ValueError("El fin del viaje debe ser posterior al inicio")
    return inicio, fin


def solapan(a, b, c, d):
    return utc(a) < utc(d) and utc(c) < utc(b)


def validar_disponibilidad(db, vehiculo, conductor, inicio, fin, excluir=None):
    for col, ident in [("vehiculos", vehiculo), ("conductores", conductor)]:
        maestro = db[col].find_one({"_id": ident})
        if not maestro or maestro.get("estado") in (
            "AVERIADO",
            "EN_MANTENIMIENTO",
            "INACTIVO",
            "SUSPENDIDO",
        ):
            raise ValueError(f"Recurso no disponible: {ident}")
    viajes = db.viajes.find(
        {
            "estado": {
                "$nin": ["FINALIZADO", "CANCELADO", "ANULADO", "INTERRUMPIDO_AVERIA"]
            },
            "$or": [
                {"vehiculo_patente": vehiculo},
                {"id_vehiculo": vehiculo},
                {"conductor_id": conductor},
                {"id_conductor": conductor},
            ],
        }
    )
    for v in viajes:
        if v["_id"] == excluir:
            continue
        # Un viaje abierto sin fin conocido no permite suponer disponibilidad futura.
        vi = (
            v.get("inicio_planificado")
            or v.get("fecha_inicio")
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        vf = v.get("fin_planificado") or datetime.max.replace(tzinfo=timezone.utc)
        if solapan(inicio, fin, vi, vf):
            raise ValueError("El vehículo o conductor tiene un viaje superpuesto")


def paradas_planificadas(puntos, datos, inicio, fin):
    suministradas = datos.get("paradas")
    if suministradas is not None:
        if [p["punto_entrega_id"] for p in suministradas] != puntos:
            raise ValueError("Las paradas deben respetar el recorrido ordenado")
        horas = [utc(p["hora_planificada"]) for p in suministradas]
    else:
        # Plan de referencia explícito y reproducible si el coordinador no indica horarios.
        horas = [
            inicio + (fin - inicio) * i / max(1, len(puntos) - 1)
            for i in range(len(puntos))
        ]
    if any(h < inicio or h > fin for h in horas) or any(
        a >= b for a, b in zip(horas, horas[1:])
    ):
        raise ValueError(
            "Los horarios deben crecer y pertenecer al intervalo del viaje"
        )
    return [
        dict(
            orden=i + 1,
            punto_entrega_id=p,
            hora_planificada=horas[i],
            estado="PENDIENTE",
        )
        for i, p in enumerate(puntos)
    ]
