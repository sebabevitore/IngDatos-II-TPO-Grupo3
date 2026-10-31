"""
Orquestador para el Caso de Uso 7: Rutas alternativas y bloqueos viales (Neo4j + Redis).
Combina:
  1. [Neo4j] Detección de rutas afectadas por el bloqueo y cálculo del camino óptimo alternativo (shortestPath).
  2. [Redis] Identificación en tiempo real de los vehículos en circulación que se dirigen al corte.
"""

from typing import Dict, Any
from app.conexiones import conectar_neo4j
from app.repositorio_rutas_alternativas import (
    identificar_viajes_afectados,
    buscar_camino_alternativo
)
from app.consulta_telemetria import consultar_estado_actual_por_viaje


def consultar_impacto_y_alternativa(
    origen_id: str,
    destino_id: str,
    punto_bloqueado_id: str
) -> Dict[str, Any]:
    driver = None
    try:
        driver = conectar_neo4j()

        # 1. Analizar el impacto del bloqueo en Neo4j (rutas y viajes en curso)
        afectados_neo4j = identificar_viajes_afectados(driver, punto_bloqueado_id)

        # 2. Cruzar con Redis para conocer la posición y estado en vivo de los vehículos afectados
        impacto_enriquecido = []
        for item in afectados_neo4j:
            ruta_id = item["ruta_afectada"]
            viajes_raw = item["viajes_afectados"]
            vehiculos_afectados = []

            for v_id in viajes_raw:
                ok, estado_redis = consultar_estado_actual_por_viaje(v_id)
                if ok:
                    vehiculos_afectados.append({
                        "viaje_id": v_id,
                        "en_circulacion": True,
                        "vehiculo_patente": estado_redis["vehiculo_patente"],
                        "latitud": estado_redis["latitud"],
                        "longitud": estado_redis["longitud"],
                        "velocidad_kmh": estado_redis["velocidad"],
                        "estado_vehiculo": estado_redis["estado_vehiculo"]
                    })
                else:
                    vehiculos_afectados.append({
                        "viaje_id": v_id,
                        "en_circulacion": False,
                        "detalle": "Sin telemetría activa en memoria"
                    })

            impacto_enriquecido.append({
                "ruta_afectada": ruta_id,
                "viajes_afectados": vehiculos_afectados
            })

        # 3. Calcular ruta de escape en el grafo (shortestPath evitando el nodo cortado)
        camino = buscar_camino_alternativo(driver, origen_id, destino_id, punto_bloqueado_id)

        return {
            "exito": True,
            "punto_bloqueado": punto_bloqueado_id,
            "impacto": impacto_enriquecido,
            "alternativa": camino if camino else "No existe ruta alternativa posible."
        }
    except Exception as e:
        return {"exito": False, "error": str(e)}
    finally:
        if driver:
            driver.close()
