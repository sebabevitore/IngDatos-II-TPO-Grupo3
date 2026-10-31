"""
Repositorio Cassandra para el Caso de Uso 4 (ETA y desvíos).
Solo lectura: consulta cuánto tardaron realmente los viajes anteriores en cada tramo.
"""

from datetime import datetime, timezone
from typing import List


def registrar_duracion_tramo(sesion, tramo_id: str, viaje_id: str, duracion_minutos: float):
    """
    Guarda cuánto tardó un viaje en completar un tramo.
    (En producción esto lo escribiría el proceso de telemetría al detectar
    que el vehículo llegó al punto destino; acá lo usamos para cargar datos de prueba.)
    """
    sesion.execute(
        """
        INSERT INTO logistica_flota.tiempos_tramo_historico
        (tramo_id, fecha_hora, viaje_id, duracion_minutos)
        VALUES (%s, %s, %s, %s)
        """,
        (tramo_id, datetime.now(timezone.utc).replace(tzinfo=None), viaje_id, duracion_minutos)
    )


def obtener_tiempos_historicos_tramo(sesion, tramo_id: str, limite: int = 5) -> List[float]:
    """
    Devuelve las duraciones (en minutos) de los últimos viajes que completaron
    ese tramo, de más reciente a más antiguo.
    """
    filas = sesion.execute(
        """
        SELECT duracion_minutos
        FROM logistica_flota.tiempos_tramo_historico
        WHERE tramo_id = %s
        LIMIT %s
        """,
        (tramo_id, limite)
    )
    return [fila.duracion_minutos for fila in filas]