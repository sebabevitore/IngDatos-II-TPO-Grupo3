"""ETA restante con posición, velocidad, horario previsto e historia del tramo."""

from datetime import datetime, timedelta, timezone
import os
from app.conexiones import conectar_mongodb, conectar_neo4j, conectar_cassandra
from app.consulta_telemetria import consultar_estado_actual_por_viaje
from app.repositorio_eta_neo4j import obtener_recorrido_viaje, obtener_tramo
from app.repositorio_eta_cassandra import obtener_tiempos_historicos_tramo
from app.geometria import distancia_km as _distancia_km, seleccionar_tramo
from app.operaciones import operacion_pendiente
from app.tiempos import utc

UMBRAL_DESVIO_KM = 0.5


def estimar_restante(tramo, historicos, fraccion, velocidad):
    base = (
        sum(historicos) / len(historicos)
        if historicos
        else float(tramo["tiempo_estimado_min"])
    )
    restante = base * (1 - fraccion)
    km = float(tramo["distancia_km"]) * (1 - fraccion)
    # Mezcla explícita: tendencia histórica/planificada y velocidad instantánea.
    # Detenido: no dividir por cero ni prometer una velocidad inexistente.
    if velocidad > 0:
        restante = (restante + 60 * km / velocidad) / 2
    return max(0, restante)


def calcular_eta_y_desvio(viaje_id):
    cliente = conectar_mongodb()
    try:
        db = cliente["logistica_flota"]
        if operacion_pendiente(db, [f"viaje:{viaje_id}"]):
            return dict(ok=False, error="Viaje con operación pendiente de recuperación")
        viaje = db.viajes.find_one({"_id": viaje_id})
        if not viaje:
            return dict(ok=False, error="Viaje inexistente")
        paradas = viaje.get("paradas", [])
    finally:
        cliente.close()
    ok, estado = consultar_estado_actual_por_viaje(viaje_id)
    if not ok:
        return dict(ok=False, error=estado)
    ahora = datetime.now(timezone.utc)
    edad = (
        ahora - datetime.fromtimestamp(estado["fecha_hora_ms"] / 1000, timezone.utc)
    ).total_seconds()
    if edad > float(os.getenv("ETA_MAX_EDAD_SEGUNDOS", "300")):
        return dict(
            ok=False,
            error="Posición desactualizada",
            edad_posicion_segundos=round(edad, 1),
        )
    if edad < -60:
        return dict(ok=False, error="Posición con fecha futura")
    neo = conectar_neo4j()
    try:
        recorrido = obtener_recorrido_viaje(neo, viaje_id)
        if len(recorrido) < 2:
            return dict(ok=False, error="Recorrido insuficiente")
        elegido = seleccionar_tramo(
            recorrido, estado["latitud"], estado["longitud"], paradas
        )
        if elegido is None:
            return dict(
                ok=True,
                viaje_id=viaje_id,
                mensaje="Recorrido completado",
                eta_minutos=0,
                desviado=False,
            )
        i, t, distancia = elegido
        actual, proximo = recorrido[i : i + 2]
        tramo = obtener_tramo(neo, actual["punto_id"], proximo["punto_id"])
        if not tramo:
            return dict(ok=False, error="Tramo no habilitado")
    finally:
        neo.close()
    cluster, cql = conectar_cassandra()
    try:
        historicos = obtener_tiempos_historicos_tramo(cql, tramo["tramo_id"])
    finally:
        cluster.shutdown()
    # Si falta historia, los horarios de las paradas definen la duración prevista.
    origen_plan = next(
        (p.get("hora_planificada") for p in paradas if p["orden"] == actual["orden"]),
        None,
    )
    destino_plan = next(
        (p.get("hora_planificada") for p in paradas if p["orden"] == proximo["orden"]),
        None,
    )
    base_planificada = "grafo"
    if origen_plan and destino_plan and utc(destino_plan) > utc(origen_plan):
        tramo = dict(
            tramo,
            tiempo_estimado_min=(utc(destino_plan) - utc(origen_plan)).total_seconds()
            / 60,
        )
        base_planificada = "horarios_paradas"
    minutos = estimar_restante(tramo, historicos, t, estado["velocidad"])
    llegada = ahora + timedelta(minutes=minutos)
    parada = next((p for p in paradas if p["orden"] == proximo["orden"]), {})
    previsto = parada.get("hora_planificada")
    demora = (
        max(0, (llegada - utc(previsto)).total_seconds() / 60) if previsto else None
    )
    cliente = conectar_mongodb()
    try:
        db = cliente["logistica_flota"]
        actualizado = db.viajes.find_one({"_id": viaje_id}) or {}
        if operacion_pendiente(db, [f"viaje:{viaje_id}"]) or actualizado.get(
            "ultima_operacion"
        ) != viaje.get("ultima_operacion"):
            return dict(
                ok=False, error="El viaje cambió durante la consulta; reintentar"
            )
    finally:
        cliente.close()
    return dict(
        ok=True,
        viaje_id=viaje_id,
        punto_actual=actual["punto_id"],
        proximo_punto=proximo["punto_id"],
        tramo_id=tramo["tramo_id"],
        eta_minutos=round(minutos, 1),
        fuente_eta="historico" if historicos else "planificado",
        base_planificada=base_planificada,
        llegada_estimada=llegada.isoformat(),
        hora_planificada=utc(previsto).isoformat() if previsto else None,
        demora_estimada_min=round(demora, 1) if demora is not None else None,
        fraccion_tramo=round(t, 4),
        velocidad_actual_kmh=estado["velocidad"],
        desviado=distancia > UMBRAL_DESVIO_KM,
        distancia_al_recorrido_km=round(distancia, 3),
    )
