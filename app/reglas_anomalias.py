import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple


def obtener_umbral_velocidad() -> float:
    """Obtiene el umbral de velocidad máxima desde .env (default: 90.0 km/h)."""
    return float(os.getenv("VELOCIDAD_MAXIMA_KMH", "90.0"))


def obtener_umbral_parada_minutos() -> float:
    """Obtiene el umbral de parada no programada desde .env (default: 10.0 min)."""
    return float(os.getenv("PARADA_MAXIMA_MINUTOS", "10.0"))


def evaluar_exceso_velocidad(
    datos: Dict[str, Any],
    umbral: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Evalúa si la medición de telemetría supera el límite de velocidad.
    Retorna el diccionario de la anomalía detectada o None si la velocidad es normal.
    """
    if umbral is None:
        umbral = obtener_umbral_velocidad()

    velocidad = float(datos.get("velocidad", 0.0))
    if velocidad > umbral:
        return {
            "tipo": "EXCESO_VELOCIDAD",
            "valor_observado": velocidad,
            "umbral": umbral,
            "descripcion": (
                f"Exceso de velocidad: {velocidad:.1f} km/h "
                f"(umbral configurado: {umbral:.1f} km/h)"
            ),
        }
    return None


def evaluar_parada_prolongada(
    datos: Dict[str, Any],
    historial_reciente: List[Dict[str, Any]],
    umbral_minutos: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Evalúa si el vehículo lleva detenido un tiempo superior al umbral permitido.
    
    Parámetros:
        datos: La medición de telemetría actual.
        historial_reciente: Lista de mediciones previas del vehículo ordenadas cronológicamente (ASC).
        umbral_minutos: Minutos máximos permitidos antes de considerarlo anomalía.
    """
    if umbral_minutos is None:
        umbral_minutos = obtener_umbral_parada_minutos()

    velocidad_actual = float(datos.get("velocidad", 0.0))
    estado_actual = str(datos.get("estado_vehiculo", "")).upper()

    # Si el vehículo está en movimiento, no hay parada
    if velocidad_actual > 0 or estado_actual == "EN_MOVIMIENTO":
        return None

    fecha_actual = datetime.fromisoformat(
        str(datos["fecha_hora"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc)

    # Buscar hacia atrás desde cuándo el vehículo está continuamente detenido (velocidad <= 0)
    inicio_detencion = fecha_actual

    for medicion in reversed(historial_reciente):
        vel = float(medicion.get("velocidad", 0.0))
        est = str(medicion.get("estado_vehiculo", "")).upper()

        if vel <= 0 or est == "DETENIDO":
            f_med = datetime.fromisoformat(
                str(medicion["fecha_hora"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            inicio_detencion = f_med
        else:
            # Hubo movimiento en este punto, acá termina el tramo continuo de detención
            break

    duracion_segundos = (fecha_actual - inicio_detencion).total_seconds()
    duracion_minutos = duracion_segundos / 60.0

    if duracion_minutos >= umbral_minutos:
        return {
            "tipo": "PARADA_NO_PROGRAMADA",
            "valor_observado": round(duracion_minutos, 2),
            "umbral": umbral_minutos,
            "descripcion": (
                f"Parada prolongada sin movimiento durante {duracion_minutos:.1f} min "
                f"(umbral configurado: {umbral_minutos:.1f} min)"
            ),
            "inicio_detencion": inicio_detencion.isoformat()
        }

    return None

