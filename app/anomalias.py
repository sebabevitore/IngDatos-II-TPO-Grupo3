"""Anomalías con ventana temporal, agenda de paradas y deduplicación durable."""

import hashlib
import os
from contextlib import ExitStack
from datetime import timedelta
from app.conexiones import conectar_mongodb, conectar_cassandra, conectar_redis
from app.operaciones import Saga
from app.tiempos import utc
from app.geometria import distancia_km
from app.reglas_anomalias import (
    evaluar_exceso_velocidad,
    evaluar_parada_prolongada,
    obtener_umbral_parada_minutos,
)
from app.repositorio_alertas import (
    guardar_alerta_cassandra,
    compensar_alerta_cassandra,
    registrar_paso_log_cassandra,
    obtener_historico_ventana,
    obtener_alertas_abiertas_cassandra,
    marcar_alerta_resuelta_cassandra,
)
from app.repositorio_alertas_redis import (
    reclamar_anomalia_redis,
    confirmar_anomalia_redis,
    compensar_claim_redis,
    clave_alerta_activa,
)


def generar_alerta_id(patente, tipo, id_evento):
    return hashlib.sha1(
        f"{patente.strip()}:{tipo.strip()}:{id_evento.strip()}".encode()
    ).hexdigest()[:16]


def es_parada_programada(db, datos):
    viaje = db.viajes.find_one({"_id": datos.get("viaje_id")}) or {}
    fecha = utc(datos["fecha_hora"])
    tolerancia = float(os.getenv("PARADA_TOLERANCIA_MINUTOS", "15"))
    for parada in viaje.get("paradas", []):
        prevista = parada.get("hora_planificada")
        if (
            not prevista
            or abs((fecha - utc(prevista)).total_seconds()) > tolerancia * 60
        ):
            continue
        punto = db.puntos_entrega.find_one({"_id": parada["punto_entrega_id"]}) or {}
        if punto.get("latitud") is None or punto.get("longitud") is None:
            continue
        if (
            distancia_km(
                float(datos["latitud"]),
                float(datos["longitud"]),
                punto["latitud"],
                punto["longitud"],
            )
            <= 0.2
        ):
            return True
    return False


def reconstruir_activa(redis, abierta):
    clave = clave_alerta_activa(abierta["vehiculo_patente"], abierta["tipo"])
    redis.hset(
        clave,
        mapping=dict(
            alerta_id=abierta["alerta_id"],
            estado="ACTIVE",
            viaje_id=abierta.get("viaje_id") or "",
            dia=str(abierta["dia"]),
            fecha_hora=abierta["fecha_hora"] or "",
            primera_vez=abierta["fecha_hora"] or "",
            ultima_vez=abierta["fecha_hora"] or "",
            cantidad="1",
        ),
    )
    redis.expire(clave, int(os.getenv("REDIS_ANOMALIA_TTL_SEGUNDOS", "120")))


def compensar_anomalia(saga, redis, cql, error):
    d = saga.doc.get("alerta")
    acciones = []
    if d and "CASSANDRA_WRITE" in saga.doc.get("pasos", []):
        acciones.append(("CASSANDRA", lambda: compensar_alerta_cassandra(cql, d)))
    if d:
        acciones.append(
            (
                "REDIS",
                lambda: compensar_claim_redis(
                    redis, d["vehiculo_patente"], d["tipo"], d["alerta_id"]
                ),
            )
        )
    return saga.compensar(acciones, error)


def procesar_anomalias_telemetria(datos, inyector=None):
    patente = datos["vehiculo_patente"].strip()
    fecha = utc(datos["fecha_hora"])
    viaje = datos.get("viaje_id")
    if not datos.get("id_evento"):
        raise ValueError("La anomalía requiere id_evento estable")
    with ExitStack() as stack:
        mongo = conectar_mongodb()
        stack.callback(mongo.close)
        db = mongo["logistica_flota"]
        cluster, cql = conectar_cassandra()
        stack.callback(cluster.shutdown)
        redis = conectar_redis()
        stack.callback(redis.close)
        historial = obtener_historico_ventana(
            cql,
            patente,
            fecha - timedelta(minutes=obtener_umbral_parada_minutos() + 2),
            fecha,
        )
        candidatas = [
            c
            for c in [
                evaluar_exceso_velocidad(datos),
                evaluar_parada_prolongada(
                    datos, historial, parada_programada=es_parada_programada(db, datos)
                ),
            ]
            if c
        ]
        tipos = {c["tipo"] for c in candidatas}
        # Una lectura normal cierra una condición; no se usa el TTL como fin de anomalía.
        for abierta in obtener_alertas_abiertas_cassandra(cql, patente):
            if abierta["tipo"] not in tipos or abierta.get("viaje_id") != viaje:
                if utc(abierta["fecha_hora"]) > fecha:
                    continue  # evento fuera de orden
                guard = Saga(
                    db,
                    "CIERRE_ANOMALIA",
                    dict(id_evento=datos["id_evento"], alerta_id=abierta["alerta_id"]),
                )
                if not guard.propia:
                    continue
                try:
                    guard.guardar(cierre=abierta)
                    guard.bloquear([f"anomalia:{patente}:{abierta['tipo']}"])
                    guard.paso(
                        "CIERRE_CASSANDRA",
                        lambda: marcar_alerta_resuelta_cassandra(
                            cql,
                            patente,
                            abierta["tipo"],
                            abierta.get("viaje_id"),
                            abierta["dia"],
                            utc(abierta["fecha_hora"]).replace(tzinfo=None),
                            abierta["alerta_id"],
                        ),
                    )
                    compensar_claim_redis(
                        redis, patente, abierta["tipo"], abierta["alerta_id"]
                    )
                    guard.completar(dict(exito=True))
                except Exception:
                    confirmado = db.operaciones.find_one({"_id": guard.id})
                    if confirmado and confirmado.get("estado") == "COMPLETADO":
                        continue
                    guard.guardar(estado="RECONCILIACION_PENDIENTE", ejecutor={})
                    raise
        procesadas = []
        for cand in candidatas:
            tipo = cand["tipo"]
            ident = generar_alerta_id(patente, tipo, str(datos["id_evento"]))
            saga = Saga(
                db,
                "ANOMALIA",
                dict(
                    id_evento=datos["id_evento"],
                    patente=patente,
                    tipo=tipo,
                    viaje_id=viaje,
                ),
            )
            if not saga.propia:
                if saga.doc["estado"] == "COMPLETADO":
                    procesadas.append(saga.doc["resultado"])
                    continue
                raise RuntimeError(f"Anomalía con operación pendiente: {saga.id}")
            try:
                saga.bloquear([f"anomalia:{patente}:{tipo}"])
                abiertas = [
                    a
                    for a in obtener_alertas_abiertas_cassandra(cql, patente)
                    if a["tipo"] == tipo
                ]
                if abiertas:
                    abierta = abiertas[0]
                    reconstruir_activa(redis, abierta)
                    resultado = dict(
                        alerta_id=abierta["alerta_id"],
                        tipo=tipo,
                        estado="DEDUPLICADA_SOSTENIDA",
                    )
                    saga.completar(resultado)
                    procesadas.append(resultado)
                    continue
                alerta = dict(
                    alerta_id=ident,
                    vehiculo_patente=patente,
                    viaje_id=viaje,
                    tipo=tipo,
                    descripcion=cand["descripcion"],
                    latitud=float(datos["latitud"]),
                    longitud=float(datos["longitud"]),
                    valor_observado=cand["valor_observado"],
                    umbral=cand["umbral"],
                    clave_deduplicacion=f'{patente}:{tipo}:{viaje or "SIN_VIAJE"}',
                    fecha_hora=fecha.isoformat(),
                    contexto=historial[-5:],
                )
                saga.guardar(alerta=alerta)

                def claim():
                    ok, _ = reclamar_anomalia_redis(
                        redis,
                        patente,
                        tipo,
                        ident,
                        viaje,
                        str(fecha.date()),
                        fecha.isoformat(),
                    )
                    if not ok:
                        raise RuntimeError(
                            "Claim Redis pendiente; ejecutar recuperación"
                        )

                saga.paso("REDIS_CLAIM", claim, inyector)
                saga.paso(
                    "CASSANDRA_WRITE",
                    lambda: guardar_alerta_cassandra(cql, alerta),
                    inyector,
                )

                def confirmar():
                    if not confirmar_anomalia_redis(redis, patente, tipo, ident):
                        reconstruir_activa(redis, dict(alerta, dia=str(fecha.date())))

                saga.paso("REDIS_CONFIRM", confirmar, inyector)
                saga.paso(
                    "NOTIFICACION",
                    lambda: print(
                        f'[ALERTA LOGÍSTICA] {patente} | {cand["descripcion"]}'
                    ),
                    inyector,
                )
                registrar_paso_log_cassandra(cql, ident, "OPERACION", "COMPLETADO")
                resultado = dict(
                    alerta_id=ident,
                    tipo=tipo,
                    estado="REGISTRADA_Y_NOTIFICADA",
                    descripcion=cand["descripcion"],
                )
                saga.completar(resultado)
                procesadas.append(resultado)
            except Exception as exc:
                confirmado = db.operaciones.find_one({"_id": saga.id})
                if confirmado and confirmado.get("estado") == "COMPLETADO":
                    procesadas.append(confirmado["resultado"])
                    continue
                if "CASSANDRA_WRITE" in saga.doc.get(
                    "pasos_completados", []
                ) or saga.db.operaciones.find_one(
                    {"_id": saga.id, "pasos_completados": "CASSANDRA_WRITE"}
                ):
                    saga.guardar(
                        estado="RECONCILIACION_PENDIENTE", error=str(exc), ejecutor={}
                    )
                else:
                    compensar_anomalia(saga, redis, cql, exc)
                raise
        return dict(
            exito=True, vehiculo_patente=patente, anomalias_detectadas=procesadas
        )
