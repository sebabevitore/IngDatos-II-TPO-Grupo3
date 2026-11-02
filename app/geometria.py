"""Geometría local del trazado disponible, sin asumir una red vial externa."""

from math import radians, cos, sin, sqrt, atan2


def distancia_km(lat1, lon1, lat2, lon2):
    a = (
        sin(radians(lat2 - lat1) / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * atan2(sqrt(min(1, a)), sqrt(max(0, 1 - a)))


def proyectar_segmento(lat, lon, a, b):
    """Distancia al segmento y fracción recorrida (proyección local equirectangular)."""
    escala = cos(radians((a["latitud"] + b["latitud"]) / 2))
    bx = radians(b["longitud"] - a["longitud"]) * 6371 * escala
    by = radians(b["latitud"] - a["latitud"]) * 6371
    px = radians(lon - a["longitud"]) * 6371 * escala
    py = radians(lat - a["latitud"]) * 6371
    den = bx * bx + by * by
    t = max(0, min(1, (px * bx + py * by) / den)) if den else 0
    return sqrt((px - t * bx) ** 2 + (py - t * by) ** 2), t


def seleccionar_tramo(recorrido, lat, lon, paradas):
    terminadas = {p.get("orden") for p in paradas if p.get("estado") == "COMPLETADA"}
    opciones = []
    for i, (a, b) in enumerate(zip(recorrido, recorrido[1:])):
        if b["orden"] in terminadas:
            continue
        d, t = proyectar_segmento(lat, lon, a, b)
        # Si está exactamente en una parada intermedia, el próximo tramo gana.
        opciones.append((d, 0 if t < 1 - 1e-7 else 1, i, t))
    if not opciones:
        return None
    _, _, i, t = min(opciones)
    return i, t, min(x[0] for x in opciones)
