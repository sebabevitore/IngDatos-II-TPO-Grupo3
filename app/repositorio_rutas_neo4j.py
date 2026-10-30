"""
Repositorio Neo4j para el Caso de Uso 1 (Planificación de un viaje).
Responsable de registrar y vincular el viaje a su recorrido en el grafo
y compensar (eliminar) el nodo si la operación falla en MongoDB o Redis.
"""

from typing import Optional, Dict, Any


def vincular_viaje_ruta_neo4j(
    driver,
    id_viaje: str,
    id_ruta: str,
    id_vehiculo: str,
    id_conductor: str
) -> Dict[str, Any]:
    """
    Registra el viaje en el grafo de Neo4j y lo vincula a la ruta planificada.
    
    Crea o asegura:
      (:Ruta {ruta_id: id_ruta})
      (:Viaje {viaje_id: id_viaje, estado: 'PLANIFICADO', ...})
      (:Viaje)-[:ASIGNADO_A]->(:Ruta)
    """
    cypher = """
    MERGE (r:Ruta {ruta_id: $id_ruta})
      ON CREATE SET r.estado = 'HABILITADA'

    MERGE (v:Viaje {viaje_id: $id_viaje})
    SET v.estado = 'PLANIFICADO',
        v.id_vehiculo = $id_vehiculo,
        v.id_conductor = $id_conductor

    MERGE (v)-[:ASIGNADO_A]->(r)
    RETURN v.viaje_id AS id_viaje, r.ruta_id AS id_ruta
    """
    with driver.session() as sesion:
        resultado = sesion.run(
            cypher,
            id_viaje=id_viaje,
            id_ruta=id_ruta,
            id_vehiculo=id_vehiculo,
            id_conductor=id_conductor
        )
        registro = resultado.single()
        return {
            "id_viaje": registro["id_viaje"] if registro else id_viaje,
            "id_ruta": registro["id_ruta"] if registro else id_ruta,
            "vinculado_en_grafo": True
        }


def compensar_viaje_neo4j(driver, id_viaje: str) -> bool:
    """
    Acción de compensación (Rollback):
    Elimina del grafo el nodo del viaje y sus relaciones si la operación
    falla posteriormente en MongoDB o al confirmar en Redis.
    """
    cypher = """
    MATCH (v:Viaje {viaje_id: $id_viaje})
    DETACH DELETE v
    """
    with driver.session() as sesion:
        resultado = sesion.run(cypher, id_viaje=id_viaje)
        consumo = resultado.consume()
        return consumo.counters.nodes_deleted > 0


def consultar_viaje_neo4j(driver, id_viaje: str) -> Optional[Dict[str, Any]]:
    """Consulta el viaje y su relación con la ruta en Neo4j."""
    cypher = """
    MATCH (v:Viaje {viaje_id: $id_viaje})
    OPTIONAL MATCH (v)-[:ASIGNADO_A]->(r:Ruta)
    RETURN v.viaje_id AS id_viaje, v.estado AS estado,
           v.id_vehiculo AS id_vehiculo, v.id_conductor AS id_conductor,
           r.ruta_id AS id_ruta
    """
    with driver.session() as sesion:
        resultado = sesion.run(cypher, id_viaje=id_viaje)
        registro = resultado.single()
        if not registro:
            return None
        return {
            "id_viaje": registro["id_viaje"],
            "estado": registro["estado"],
            "id_vehiculo": registro["id_vehiculo"],
            "id_conductor": registro["id_conductor"],
            "id_ruta": registro["id_ruta"]
        }

