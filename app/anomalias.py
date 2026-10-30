import hashlib
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from app.conexiones import conectar_cassandra, conectar_redis
from app.reglas_anomalias import (
    evaluar_exceso_velocidad,
    evaluar_parada_prolongada,
)
from app.repositorio_alertas import (
    guardar_alerta_cassandra,
    compensar_alerta_cassandra,
    registrar_paso_log_cassandra,
    obtener_historico_telemetria_reciente,
    marcar_alerta_resuelta_cassandra,
)
from app.repositorio_alertas_redis import (
    reclamar_anomalia_redis,
    confirmar_anomalia_redis,
    compensar_claim_redis,
    resolver_anomalia_redis,
    obtener_alerta_activa_redis,
)
from app.fallas import InyectorFallas, FallaSimuladaError


def generar_alerta_id(patente: str, tipo: str, id_evento: str) -> str:
    """Genera un identificador determinístico para garantizar idempotencia estricta."""
    semilla = f"{patente.strip()}:{tipo.strip()}:{id_evento.strip()}"
    return hashlib.sha1(semilla.encode("utf-8")).hexdigest()[:16]


def procesar_anomalias_telemetria(
    datos: Dict[str, Any],
    inyector: Optional[InyectorFallas] = None
) -> Dict[str, Any]:
    """
    Orquestador principal del Caso de Uso 3: Detección de anomalías.
    
    Implementa el flujo:
      1. Evaluación de reglas de negocio.
      2. Claim atómico en Redis (evita alertas duplicadas por condición sostenida).
      3. Persistencia durable en Cassandra (fuente de la verdad).
         -> Si falla Cassandra: ROLLBACK compensatorio borrando el claim en Redis.
      4. Confirmación de estado ACTIVE en Redis.
      5. Emisión de la alerta.
    
    Registra cada paso en alertas_log_pasos de Cassandra (requisito Sección 5).
    """
    patente = datos["vehiculo_patente"].strip()
    viaje_id = datos.get("viaje_id")
    id_evento = str(datos.get("id_evento", ""))

    fecha = datetime.fromisoformat(
        str(datos["fecha_hora"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    dia = fecha.date()
    fecha_iso = fecha.isoformat()

    cluster = None
    cliente_redis = None

    anomalias_procesadas = []

    try:
        cluster, sesion = conectar_cassandra()
        cliente_redis = conectar_redis()

        # 1. Recuperar contexto histórico reciente de Cassandra (últimas lecturas)
        historial_reciente = obtener_historico_telemetria_reciente(
            sesion, patente, dia, limite=15
        )

        # 2. Evaluar reglas de negocio
        candidatas = []
        anomalia_vel = evaluar_exceso_velocidad(datos)
        if anomalia_vel:
            candidatas.append(anomalia_vel)

        anomalia_parada = evaluar_parada_prolongada(datos, historial_reciente)
        if anomalia_parada:
            candidatas.append(anomalia_parada)

        # 3. Procesar cada anomalía detectada
        ttl_pending = int(os.getenv("REDIS_ANOMALIA_PENDING_TTL_SEGUNDOS", "30"))
        ttl_activo = int(os.getenv("REDIS_ANOMALIA_TTL_SEGUNDOS", "120"))

        for cand in candidatas:
            tipo = cand["tipo"]
            alerta_id = generar_alerta_id(patente, tipo, id_evento)

            datos_alerta = {
                "alerta_id": alerta_id,
                "vehiculo_patente": patente,
                "viaje_id": viaje_id,
                "tipo": tipo,
                "descripcion": cand["descripcion"],
                "latitud": float(datos.get("latitud", 0.0)),
                "longitud": float(datos.get("longitud", 0.0)),
                "valor_observado": cand["valor_observado"],
                "umbral": cand["umbral"],
                "clave_deduplicacion": f"{patente}:{tipo}:{viaje_id or 'SIN_VIAJE'}",
                "fecha_hora": fecha_iso,
                "contexto": historial_reciente[-5:] if historial_reciente else []
            }

            # --- PASO 1: CLAIM EN REDIS (Árbitro atómico de concurrencia) ---
            if inyector:
                inyector.verificar("REDIS_CLAIM")

            claim_exitoso, motivo_redis = reclamar_anomalia_redis(
                cliente_redis,
                patente=patente,
                tipo=tipo,
                alerta_id=alerta_id,
                viaje_id=viaje_id,
                dia=str(dia),
                fecha_hora_iso=fecha_iso,
                ttl_pending=ttl_pending,
                ttl_activo=ttl_activo
            )

            if not claim_exitoso:
                # La anomalía ya está activa y fue sostenida. No duplicamos en Cassandra.
                anomalias_procesadas.append({
                    "alerta_id": alerta_id,
                    "tipo": tipo,
                    "estado": "DEDUPLICADA_SOSTENIDA",
                    "mensaje": "Anomalía en curso; TTL renovado en Redis sin duplicar en Cassandra"
                })
                continue

            # --- PASO 2: PERSISTENCIA EN CASSANDRA (Fuente duradera de la verdad) ---
            registrar_paso_log_cassandra(
                sesion, alerta_id, "CASSANDRA_WRITE", "INICIADO",
                f"Persistiendo alerta {tipo} en Cassandra"
            )

            try:
                if inyector:
                    inyector.verificar("CASSANDRA_WRITE")

                guardar_alerta_cassandra(sesion, datos_alerta)

                registrar_paso_log_cassandra(
                    sesion, alerta_id, "CASSANDRA_WRITE", "COMPLETADO"
                )
            except Exception as err_cassandra:
                # COMPENSACIÓN (ROLLBACK):
                # Si falló la escritura duradera, liberamos el claim de Redis
                compensar_claim_redis(cliente_redis, patente, tipo, alerta_id)

                try:
                    registrar_paso_log_cassandra(
                        sesion, alerta_id, "CASSANDRA_WRITE", "ROLLBACK_COMPENSADO",
                        f"Fallo en Cassandra: {err_cassandra}. Claim liberado en Redis."
                    )
                except Exception:
                    pass

                raise RuntimeError(
                    f"Fallo en persistencia de Cassandra para alerta {tipo}. "
                    f"Rollback completado (claim de Redis liberado). Detalle: {err_cassandra}"
                ) from err_cassandra

            # --- PASO 3: CONFIRMACIÓN EN REDIS (PENDING -> ACTIVE) ---
            registrar_paso_log_cassandra(
                sesion, alerta_id, "REDIS_CONFIRM", "INICIADO"
            )

            try:
                if inyector:
                    inyector.verificar("REDIS_CONFIRM")

                confirmado = confirmar_anomalia_redis(
                    cliente_redis, patente, tipo, alerta_id, ttl_activo=ttl_activo
                )

                registrar_paso_log_cassandra(
                    sesion, alerta_id, "REDIS_CONFIRM",
                    "COMPLETADO" if confirmado else "ALERTA_ID_MISMATCH"
                )
            except Exception as err_redis_conf:
                # Cassandra YA tiene el evento persistido (es durable).
                # No compensamos borrando de Cassandra; dejamos registrado para que el
                # proceso de reconciliación promueva o repare el estado en Redis.
                registrar_paso_log_cassandra(
                    sesion, alerta_id, "REDIS_CONFIRM", "ERROR_PENDIENTE_RECONCILIACION",
                    str(err_redis_conf)
                )
                raise RuntimeError(
                    f"Alerta guardada en Cassandra pero falló confirmación en Redis. "
                    f"Queda pendiente para reconciliador. Detalle: {err_redis_conf}"
                ) from err_redis_conf

            # --- PASO 4: EMISIÓN DE LA ALERTA (Notificación) ---
            registrar_paso_log_cassandra(
                sesion, alerta_id, "NOTIFICACION", "INICIADO"
            )

            try:
                if inyector:
                    inyector.verificar("NOTIFICACION")

                # Simulación de emisión al despachador / consola
                mensaje_alerta = (
                    f"[ALERTA LOGÍSTICA] Vehículo {patente} | "
                    f"Tipo: {tipo} | {cand['descripcion']}"
                )
                print(mensaje_alerta)

                registrar_paso_log_cassandra(
                    sesion, alerta_id, "NOTIFICACION", "COMPLETADO", mensaje_alerta
                )
            except Exception as err_notif:
                registrar_paso_log_cassandra(
                    sesion, alerta_id, "NOTIFICACION", "ERROR", str(err_notif)
                )
                # La alerta ya está guardada y activa en ambos motores; el fallo de notificación
                # se registra para reintento at-least-once.
                raise

            anomalias_procesadas.append({
                "alerta_id": alerta_id,
                "tipo": tipo,
                "estado": "REGISTRADA_Y_NOTIFICADA",
                "descripcion": cand["descripcion"]
            })

        return {
            "exito": True,
            "vehiculo_patente": patente,
            "anomalias_detectadas": anomalias_procesadas
        }

    finally:
        if cluster is not None:
            try:
                cluster.shutdown()
            except Exception:
                pass
        if cliente_redis is not None:
            try:
                cliente_redis.close()
            except Exception:
                pass

