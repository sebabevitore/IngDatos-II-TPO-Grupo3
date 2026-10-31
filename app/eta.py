"""
Orquestador para el Caso de Uso 4: ETA y desvíos (Redis + Neo4j + Cassandra).
Caso de solo lectura: no escribe en ningún motor, solo combina datos.

Paso 1: [Redis] Posición, velocidad y estado actual del vehículo.
Paso 2: [Neo4j] Recorrido planificado del viaje y datos del próximo tramo.
Paso 3: [Cassandra] Tiempos históricos reales de ese mismo tramo.
Paso 4: Cálculo del ETA y detección de desvío.
"""

from math import radians, sin, cos, sqrt, atan2
from typing import Dict, Any

from app.conexiones import conectar_redis, conectar_neo4j, conectar_cassandra
from app.consulta_telemetria import consultar_estado_actual_por_viaje
from app.repositorio_eta_neo4j import obtener_recorrido_viaje, obtener_tramo
from app.repositorio_eta_cassandra import obtener_tiempos_historicos_tramo

UMBRAL_DESVIO_KM = 0.5  # a partir de esta distancia del recorrido, se considera desvío


def _distancia_km(lat1, lon1, lat2, lon2) -> float:
    """Distancia entre dos coordenadas (fórmula de Haversine), en kilómetros."""
    radio_tierra = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return radio_tierra * 2 * atan2(sqrt(a), sqrt(1 - a))


def calcular_eta_y_desvio(viaje_id: str) -> Dict[str, Any]:
    # Paso 1: posición actual en Redis
    ok, estado = consultar_estado_actual_por_viaje(viaje_id)
    if not ok:
        return {"ok": False, "error": estado}

    lat_actual = estado["latitud"]
    lon_actual = estado["longitud"]

    # Paso 2: recorrido planificado en Neo4j
    driver = conectar_neo4j()
    try:
        recorrido = obtener_recorrido_viaje(driver, viaje_id)
        if not recorrido:
            return {"ok": False, "error": "El viaje no tiene recorrido planificado en Neo4j"}

        # Punto más cercano a la posición actual (por proximidad)
        distancias = [
            (p, _distancia_km(lat_actual, lon_actual, p["latitud"], p["longitud"]))
            for p in recorrido
        ]
        punto_actual, distancia_al_punto = min(distancias, key=lambda par: par[1])
        indice_actual = recorrido.index(punto_actual)

        desviado = distancia_al_punto > UMBRAL_DESVIO_KM

        if indice_actual + 1 >= len(recorrido):
            return {
                "ok": True,
                "viaje_id": viaje_id,
                "mensaje": "El vehículo ya está en el último punto del recorrido",
                "desviado": desviado,
            }

        proximo_punto = recorrido[indice_actual + 1]
        tramo = obtener_tramo(driver, punto_actual["punto_id"], proximo_punto["punto_id"])
        if not tramo:
            return {"ok": False, "error": "No se encontró el tramo planificado en el grafo"}
    finally:
        driver.close()

    # Paso 3: tiempos históricos reales en Cassandra
    cluster, sesion = conectar_cassandra()
    try:
        historicos = obtener_tiempos_historicos_tramo(sesion, tramo["tramo_id"])
    finally:
        cluster.shutdown()

    # Paso 4: cálculo del ETA
    if historicos:
        eta_minutos = sum(historicos) / len(historicos)  # promedio de lo que tardaron en la realidad
        fuente_eta = "historico"
    else:
        eta_minutos = tramo["tiempo_estimado_min"]  # no hay historial: usamos lo planificado
        fuente_eta = "planificado"

    return {
        "ok": True,
        "viaje_id": viaje_id,
        "punto_actual": punto_actual["punto_id"],
        "proximo_punto": proximo_punto["punto_id"],
        "tramo_id": tramo["tramo_id"],
        "eta_minutos": round(eta_minutos, 1),
        "fuente_eta": fuente_eta,
        "desviado": desviado,
        "distancia_al_recorrido_km": round(distancia_al_punto, 3),
    }
