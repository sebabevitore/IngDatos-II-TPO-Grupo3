"""
Repositorio Neo4j para el Caso de Uso 4 (ETA y desvíos).
Solo lectura: consulta el recorrido planificado y los tramos del grafo.
"""

from typing import List, Dict, Any, Optional


def obtener_recorrido_viaje(driver, viaje_id: str) -> List[Dict[str, Any]]:
    """
    Devuelve los puntos de entrega de la ruta asignada a un viaje,
    en el orden en que deben visitarse.
    """
    cypher = """
    MATCH (v:Viaje {viaje_id: $viaje_id})-[:ASIGNADO_A]->(r:Ruta)-[inc:INCLUYE]->(p:PuntoEntrega)
    RETURN p.punto_entrega_id AS punto_id, p.nombre AS nombre,
           p.latitud AS latitud, p.longitud AS longitud, inc.orden AS orden
    ORDER BY inc.orden
    """
    with driver.session() as sesion:
        resultado = sesion.run(cypher, viaje_id=viaje_id)
        return [dict(registro) for registro in resultado]


def obtener_tramo(driver, punto_origen_id: str, punto_destino_id: str) -> Optional[Dict[str, Any]]:
    """
    Devuelve la distancia y el tiempo estimado planificado entre dos puntos
    de entrega conectados y habilitados en el grafo.
    """
    cypher = """
    MATCH (a:PuntoEntrega {punto_entrega_id: $origen})-[c:CONECTA]->(b:PuntoEntrega {punto_entrega_id: $destino})
    WHERE c.habilitado = true
    RETURN c.tramo_id AS tramo_id, c.distancia_km AS distancia_km,
           c.tiempo_estimado_min AS tiempo_estimado_min
    """
    with driver.session() as sesion:
        resultado = sesion.run(cypher, origen=punto_origen_id, destino=punto_destino_id)
        registro = resultado.single()
        return dict(registro) if registro else None