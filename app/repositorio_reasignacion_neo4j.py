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
    puntos_destino: List[str],
) -> Dict[str, Any]:
    """
    Paso 2 del Saga:
    1. Valida que el punto de avería exista en el grafo.
    2. Vincula el viaje original como interrumpido en ese punto.
    3. Crea el nodo del viaje de rescate y la relación [:RESCATA_A].
    4. Vincula los tramos restantes que el nuevo vehículo deberá completar.
    """
    if not puntos_destino:
        raise ValueError("No hay destinos de rescate")
    recorrido = [id_punto_averia]
    ruta_id = f"RESCATE-{id_viaje_rescate}"
    with driver.session() as sesion:
        # Calcular y validar todo antes de escribir el grafo.
        for destino in dict.fromkeys(puntos_destino):
            if destino == recorrido[-1]:
                continue
            fila = sesion.run(
                "MATCH p=shortestPath((a:PuntoEntrega {punto_entrega_id:$a})-[:CONECTA*]->(b:PuntoEntrega {punto_entrega_id:$b})) "
                "WHERE all(r IN relationships(p) WHERE r.habilitado=true) RETURN [n IN nodes(p)|n.punto_entrega_id] AS puntos",
                a=recorrido[-1],
                b=destino,
            ).single()
            if not fila:
                raise ValueError("No existe un recorrido habilitado para el rescate")
            recorrido.extend(fila["puntos"][1:])

        def escribir(tx):
            tx.run(
                "MATCH (v:Viaje {viaje_id:$viejo}),(p:PuntoEntrega {punto_entrega_id:$averia}) "
                "SET v.estado='INTERRUMPIDO_AVERIA' MERGE (v)-[:INTERRUMPIDO_EN]->(p) "
                "CREATE (n:Viaje {viaje_id:$nuevo,estado:'EN_CURSO',tipo:'RESCATE'}) "
                "CREATE (r:Ruta {ruta_id:$ruta,estado:'HABILITADA'}) CREATE (n)-[:ASIGNADO_A]->(r) "
                "CREATE (n)-[:RESCATA_A]->(v) CREATE (n)-[:PARTE_DESDE]->(p)",
                viejo=id_viaje_averiado,
                averia=id_punto_averia,
                nuevo=id_viaje_rescate,
                ruta=ruta_id,
            ).consume()
            for i, p in enumerate(recorrido):
                tx.run(
                    "MATCH (r:Ruta {ruta_id:$ruta}),(p:PuntoEntrega {punto_entrega_id:$p}) CREATE (r)-[:INCLUYE {orden:$orden}]->(p)",
                    ruta=ruta_id,
                    p=p,
                    orden=i + 1,
                ).consume()

        sesion.execute_write(escribir)
    return dict(
        id_viaje_rescate=id_viaje_rescate,
        punto_averia=id_punto_averia,
        puntos_asignados_en_grafo=len(puntos_destino),
        ruta_id=ruta_id,
        recorrido=recorrido,
    )


def compensar_rescate_neo4j(driver, id_viaje_rescate: str, id_viaje_averiado: str):
    """
    Acción de compensación (Rollback):
    Si falla el paso posterior (MongoDB), elimina del grafo el viaje de rescate
    y retira la marca de interrupción del viaje original, dejándolo en su estado previo.
    """
    with driver.session() as sesion:

        def compensar(tx):
            tx.run(
                "MATCH (v:Viaje {viaje_id:$nuevo}) DETACH DELETE v",
                nuevo=id_viaje_rescate,
            ).consume()
            tx.run(
                "MATCH (r:Ruta {ruta_id:$ruta}) WHERE NOT EXISTS { MATCH (:Viaje)-[:ASIGNADO_A]->(r) } DETACH DELETE r",
                ruta=f"RESCATE-{id_viaje_rescate}",
            ).consume()
            tx.run(
                "MATCH (v:Viaje {viaje_id:$viejo}) OPTIONAL MATCH (v)-[r:INTERRUMPIDO_EN]->() DELETE r SET v.estado='EN_CURSO'",
                viejo=id_viaje_averiado,
            ).consume()

        sesion.execute_write(compensar)
