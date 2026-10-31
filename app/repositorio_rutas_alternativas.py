from typing import List, Dict, Any, Optional

def identificar_viajes_afectados(driver, punto_bloqueado_id: str) -> List[Dict[str, Any]]:
    """Encuentra rutas que incluyen el punto bloqueado y lista los viajes EN_CURSO afectados."""
    cypher = """
    MATCH (p:PuntoEntrega {punto_entrega_id: $punto_bloqueado})<-[:INCLUYE]-(r:Ruta)
    OPTIONAL MATCH (v:Viaje {estado: 'EN_CURSO'})-[:ASIGNADO_A]->(r)
    RETURN r.ruta_id AS ruta_afectada, collect(v.viaje_id) AS viajes_afectados
    """
    with driver.session() as sesion:
        resultado = sesion.run(cypher, punto_bloqueado=punto_bloqueado_id)
        return [dict(registro) for registro in resultado]

def buscar_camino_alternativo(
    driver, origen_id: str, destino_id: str, punto_bloqueado_id: str
) -> Optional[Dict[str, Any]]:
    """Calcula el camino más corto esquivando el nodo bloqueado y sumando métricas."""
    cypher = """
    MATCH p = shortestPath((origen:PuntoEntrega {punto_entrega_id: $origen})-[:CONECTA*]-(destino:PuntoEntrega {punto_entrega_id: $destino}))
    WHERE NONE(nodo IN nodes(p) WHERE nodo.punto_entrega_id = $bloqueado)
      AND ALL(rel IN relationships(p) WHERE rel.habilitado = true)
    RETURN [n IN nodes(p) | n.punto_entrega_id] AS recorrido,
           reduce(tiempo = 0, r IN relationships(p) | tiempo + r.tiempo_estimado_min) AS tiempo_total,
           reduce(dist = 0, r IN relationships(p) | dist + r.distancia_km) AS distancia_total
    """
    with driver.session() as sesion:
        resultado = sesion.run(
            cypher, 
            origen=origen_id, 
            destino=destino_id, 
            bloqueado=punto_bloqueado_id
        )
        registro = resultado.single()
        return dict(registro) if registro else None