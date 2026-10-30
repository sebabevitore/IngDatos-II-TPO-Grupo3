"""
Repositorio Neo4j para el Caso de Uso 5 (Reasignación por avería).
Responsable de verificar la red vial, validar conectividad desde el punto
de la avería hasta los destinos restantes y vincular el nuevo viaje de rescate en el grafo.
"""

from typing import List, Dict, Any, Optional


def asegurar_red_prueba_neo4j(driver):
    """
    Carga nodos y tramos de prueba si el grafo está vacío,
    garantizando que la red logística sea navegable para las pruebas.
    """
    cypher = """
    MERGE (p1:PuntoEntrega {punto_entrega_id: 'PUNTO-CENTRO'})
      ON CREATE SET p1.nombre = 'Centro Logístico Principal', p1.localidad = 'CABA', p1.latitud = -34.6037, p1.longitud = -58.3816
    MERGE (p2:PuntoEntrega {punto_entrega_id: 'PUNTO-NORTE'})
      ON CREATE SET p2.nombre = 'Depósito Norte', p2.localidad = 'San Isidro', p2.latitud = -34.4716, p2.longitud = -58.5284
    MERGE (p3:PuntoEntrega {punto_entrega_id: 'PUNTO-OESTE'})
      ON CREATE SET p3.nombre = 'Planta Distribución Oeste', p3.localidad = 'Morón', p3.latitud = -34.6534, p3.longitud = -58.6198
    MERGE (p4:PuntoEntrega {punto_entrega_id: 'PUNTO-SUR'})
      ON CREATE SET p4.nombre = 'Centro Entrega Sur', p4.localidad = 'Avellaneda', p4.latitud = -34.6611, p4.longitud = -58.3644

    MERGE (p1)-[c1:CONECTA {tramo_id: 'T-CENTRO-NORTE'}]->(p2)
      ON CREATE SET c1.distancia_km = 22.5, c1.tiempo_estimado_min = 35, c1.habilitado = true
    MERGE (p2)-[c2:CONECTA {tramo_id: 'T-NORTE-CENTRO'}]->(p1)
      ON CREATE SET c2.distancia_km = 22.5, c2.tiempo_estimado_min = 35, c2.habilitado = true

    MERGE (p1)-[c3:CONECTA {tramo_id: 'T-CENTRO-OESTE'}]->(p3)
      ON CREATE SET c3.distancia_km = 28.0, c3.tiempo_estimado_min = 45, c3.habilitado = true
    MERGE (p1)-[c4:CONECTA {tramo_id: 'T-CENTRO-SUR'}]->(p4)
      ON CREATE SET c4.distancia_km = 12.0, c4.tiempo_estimado_min = 20, c4.habilitado = true
    """
    with driver.session() as sesion:
        sesion.run(cypher)


def vincular_rescate_neo4j(
    driver,
    id_viaje_averiado: str,
    id_viaje_rescate: str,
    id_punto_averia: str,
    puntos_destino: List[str]
) -> Dict[str, Any]:
    """
    Paso 2 del Saga:
    1. Valida que el punto de avería exista en el grafo.
    2. Vincula el viaje original como interrumpido en ese punto.
    3. Crea el nodo del viaje de rescate y la relación [:RESCATA_A].
    4. Vincula los tramos restantes que el nuevo vehículo deberá completar.
    """
    asegurar_red_prueba_neo4j(driver)

    cypher = """
    MATCH (pa:PuntoEntrega {punto_entrega_id: $id_punto_averia})
    MERGE (v_orig:Viaje {viaje_id: $id_viaje_averiado})
    SET v_orig.estado = 'INTERRUMPIDO_AVERIA'

    MERGE (v_orig)-[r_int:INTERRUMPIDO_EN]->(pa)

    MERGE (v_resc:Viaje {viaje_id: $id_viaje_rescate})
    SET v_resc.estado = 'EN_CURSO',
        v_resc.tipo = 'RESCATE'

    MERGE (v_resc)-[:RESCATA_A]->(v_orig)
    MERGE (v_resc)-[:PARTE_DESDE]->(pa)

    WITH v_resc
    UNWIND range(0, size($puntos_destino) - 1) AS idx
    WITH v_resc, idx, $puntos_destino[idx] AS id_dest
    MATCH (pd:PuntoEntrega {punto_entrega_id: id_dest})
    MERGE (v_resc)-[:DEBE_ENTREGAR_EN {orden: idx + 1}]->(pd)
    RETURN count(pd) AS puntos_vinculados
    """

    with driver.session() as sesion:
        resultado = sesion.run(
            cypher,
            id_viaje_averiado=id_viaje_averiado,
            id_viaje_rescate=id_viaje_rescate,
            id_punto_averia=id_punto_averia,
            puntos_destino=puntos_destino
        )
        registro = resultado.single()
        puntos_count = registro["puntos_vinculados"] if registro else 0

    return {
        "id_viaje_rescate": id_viaje_rescate,
        "punto_averia": id_punto_averia,
        "puntos_asignados_en_grafo": puntos_count
    }


def compensar_rescate_neo4j(
    driver,
    id_viaje_rescate: str,
    id_viaje_averiado: str
):
    """
    Acción de compensación (Rollback):
    Si falla el paso posterior (MongoDB), elimina del grafo el viaje de rescate
    y retira la marca de interrupción del viaje original, dejándolo en su estado previo.
    """
    cypher = """
    // 1. Eliminar completamente el nodo de rescate y todas sus relaciones
    OPTIONAL MATCH (v_resc:Viaje {viaje_id: $id_viaje_rescate})
    DETACH DELETE v_resc

    // 2. Restaurar el viaje original en el grafo
    WITH 1 AS dummy
    OPTIONAL MATCH (v_orig:Viaje {viaje_id: $id_viaje_averiado})-[r:INTERRUMPIDO_EN]->()
    DELETE r
    WITH v_orig
    WHERE v_orig IS NOT NULL
    SET v_orig.estado = 'EN_CURSO'
    """
    with driver.session() as sesion:
        sesion.run(
            cypher,
            id_viaje_rescate=id_viaje_rescate,
            id_viaje_averiado=id_viaje_averiado
        )

