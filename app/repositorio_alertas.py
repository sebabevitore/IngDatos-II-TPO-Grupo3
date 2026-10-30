import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


def guardar_alerta_cassandra(sesion, datos_alerta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inserta la alerta en el histórico de Cassandra y en la tabla de alertas abiertas.
    
    Tablas afectadas:
      1. alertas_por_vehiculo_dia (siempre)
      2. alertas_por_viaje_dia (si la alerta tiene viaje_id)
      3. alertas_abiertas_por_vehiculo (espejo durable para reconciliación)
      
    Las escrituras en Cassandra son idempotentes: reescribir con la misma
    clave primaria no duplica filas.
    """
    patente = datos_alerta["vehiculo_patente"].strip()
    viaje_id = datos_alerta.get("viaje_id")
    if viaje_id:
        viaje_id = viaje_id.strip()

    # Normalizar fecha
    fecha = datetime.fromisoformat(
        str(datos_alerta["fecha_hora"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    dia = fecha.date()
    fecha_cql = fecha.replace(tzinfo=None)

    alerta_id = str(datos_alerta["alerta_id"])
    tipo = str(datos_alerta["tipo"])
    descripcion = str(datos_alerta["descripcion"])
    latitud = float(datos_alerta.get("latitud", 0.0))
    longitud = float(datos_alerta.get("longitud", 0.0))
    valor_obs = float(datos_alerta.get("valor_observado", 0.0))
    umbral = float(datos_alerta.get("umbral", 0.0))
    clave_dedup = str(datos_alerta.get("clave_deduplicacion", f"{patente}:{tipo}:{viaje_id or 'SIN_VIAJE'}"))
    resuelta = bool(datos_alerta.get("resuelta", False))
    contexto = datos_alerta.get("contexto")
    contexto_str = json.dumps(contexto) if isinstance(contexto, (dict, list)) else (contexto or "{}")

    # 1. Insertar en alertas_por_vehiculo_dia
    sesion.execute(
        """
        INSERT INTO logistica_flota.alertas_por_vehiculo_dia
        (vehiculo_patente, dia, fecha_hora, alerta_id, viaje_id, tipo,
         descripcion, latitud, longitud, valor_observado, umbral,
         clave_deduplicacion, resuelta, fecha_resolucion, contexto)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            patente, dia, fecha_cql, alerta_id, viaje_id, tipo,
            descripcion, latitud, longitud, valor_obs, umbral,
            clave_dedup, resuelta, None, contexto_str
        )
    )

    # 2. Insertar en alertas_por_viaje_dia (si corresponde)
    if viaje_id:
        sesion.execute(
            """
            INSERT INTO logistica_flota.alertas_por_viaje_dia
            (viaje_id, dia, fecha_hora, alerta_id, vehiculo_patente, tipo,
             descripcion, latitud, longitud, valor_observado, umbral,
             clave_deduplicacion, resuelta, fecha_resolucion, contexto)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                viaje_id, dia, fecha_cql, alerta_id, patente, tipo,
                descripcion, latitud, longitud, valor_obs, umbral,
                clave_dedup, resuelta, None, contexto_str
            )
        )

    # 3. Registrar en alertas_abiertas_por_vehiculo si no está resuelta
    if not resuelta:
        sesion.execute(
            """
            INSERT INTO logistica_flota.alertas_abiertas_por_vehiculo
            (vehiculo_patente, tipo, alerta_id, viaje_id, dia, fecha_hora)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (patente, tipo, alerta_id, viaje_id, dia, fecha_cql)
        )

    return {
        "alerta_id": alerta_id,
        "vehiculo_patente": patente,
        "viaje_id": viaje_id,
        "tipo": tipo,
        "guardado_en_cassandra": True
    }


def compensar_alerta_cassandra(sesion, datos_alerta: Dict[str, Any]):
    """
    Acción de compensación (Rollback): Si un paso posterior falló, elimina los registros
    creados en Cassandra para preservar la consistencia global.
    """
    patente = datos_alerta["vehiculo_patente"].strip()
    viaje_id = datos_alerta.get("viaje_id")
    alerta_id = str(datos_alerta["alerta_id"])
    tipo = str(datos_alerta["tipo"])

    fecha = datetime.fromisoformat(
        str(datos_alerta["fecha_hora"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    dia = fecha.date()
    fecha_cql = fecha.replace(tzinfo=None)

    # Borrar de histórico por vehículo
    sesion.execute(
        """
        DELETE FROM logistica_flota.alertas_por_vehiculo_dia
        WHERE vehiculo_patente = %s AND dia = %s AND fecha_hora = %s AND alerta_id = %s
        """,
        (patente, dia, fecha_cql, alerta_id)
    )

    # Borrar de histórico por viaje (si aplica)
    if viaje_id:
        sesion.execute(
            """
            DELETE FROM logistica_flota.alertas_por_viaje_dia
            WHERE viaje_id = %s AND dia = %s AND fecha_hora = %s AND alerta_id = %s
            """,
            (viaje_id, dia, fecha_cql, alerta_id)
        )

    # Borrar de alertas abiertas
    sesion.execute(
        """
        DELETE FROM logistica_flota.alertas_abiertas_por_vehiculo
        WHERE vehiculo_patente = %s AND tipo = %s
        """,
        (patente, tipo)
    )


def registrar_paso_log_cassandra(
    sesion,
    alerta_id: str,
    paso: str,
    estado: str,
    detalle: Optional[str] = None
):
    """
    Registra el avance de los pasos en Cassandra (requisito obligatorio Sección 5).
    Estados típicos: 'INICIADO', 'COMPLETADO', 'COMPENSADO', 'ERROR'.
    """
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    sesion.execute(
        """
        INSERT INTO logistica_flota.alertas_log_pasos
        (alerta_id, ts, paso, estado, detalle)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (alerta_id, ahora, paso, estado, detalle or "")
    )


def marcar_alerta_resuelta_cassandra(
    sesion,
    patente: str,
    tipo: str,
    viaje_id: Optional[str],
    dia,
    fecha_hora,
    alerta_id: str
):
    """Marca la alerta como resuelta en el histórico y la remueve de alertas abiertas."""
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    fecha_cql = fecha_hora.replace(tzinfo=None) if hasattr(fecha_hora, "replace") else fecha_hora

    # Actualizar tabla por vehículo
    sesion.execute(
        """
        UPDATE logistica_flota.alertas_por_vehiculo_dia
        SET resuelta = true, fecha_resolucion = %s
        WHERE vehiculo_patente = %s AND dia = %s AND fecha_hora = %s AND alerta_id = %s
        """,
        (ahora, patente, dia, fecha_cql, alerta_id)
    )

    # Actualizar tabla por viaje si aplica
    if viaje_id:
        sesion.execute(
            """
            UPDATE logistica_flota.alertas_por_viaje_dia
            SET resuelta = true, fecha_resolucion = %s
            WHERE viaje_id = %s AND dia = %s AND fecha_hora = %s AND alerta_id = %s
            """,
            (ahora, viaje_id, dia, fecha_cql, alerta_id)
        )

    # Borrar de alertas abiertas
    sesion.execute(
        """
        DELETE FROM logistica_flota.alertas_abiertas_por_vehiculo
        WHERE vehiculo_patente = %s AND tipo = %s
        """,
        (patente, tipo)
    )


def obtener_alertas_abiertas_cassandra(sesion, patente: Optional[str] = None) -> List[Dict[str, Any]]:
    """Consulta las alertas activas directamente desde Cassandra."""
    if patente:
        filas = sesion.execute(
            """
            SELECT * FROM logistica_flota.alertas_abiertas_por_vehiculo
            WHERE vehiculo_patente = %s
            """,
            (patente,)
        )
    else:
        filas = sesion.execute(
            "SELECT * FROM logistica_flota.alertas_abiertas_por_vehiculo"
        )

    resultados = []
    for fila in filas:
        resultados.append({
            "vehiculo_patente": fila.vehiculo_patente,
            "tipo": fila.tipo,
            "alerta_id": fila.alerta_id,
            "viaje_id": fila.viaje_id,
            "dia": str(fila.dia),
            "fecha_hora": fila.fecha_hora.isoformat() if fila.fecha_hora else None
        })
    return resultados


def obtener_historico_telemetria_reciente(
    sesion,
    patente: str,
    dia,
    limite: int = 20
) -> List[Dict[str, Any]]:
    """Recupera las últimas mediciones de telemetría de un vehículo para contexto y análisis."""
    filas = sesion.execute(
        """
        SELECT fecha_hora, id_evento, latitud, longitud, velocidad, estado_vehiculo
        FROM logistica_flota.telemetria_por_vehiculo_dia
        WHERE vehiculo_patente = %s AND dia = %s
        ORDER BY fecha_hora DESC, id_evento DESC
        LIMIT %s
        """,
        (patente, dia, limite)
    )

    registros = []
    for f in filas:
        registros.append({
            "fecha_hora": f.fecha_hora.isoformat() if f.fecha_hora else "",
            "id_evento": str(f.id_evento),
            "latitud": f.latitud,
            "longitud": f.longitud,
            "velocidad": f.velocidad,
            "estado_vehiculo": f.estado_vehiculo
        })

    # Retornar en orden cronológico ascendente (ASC)
    registros.reverse()
    return registros

