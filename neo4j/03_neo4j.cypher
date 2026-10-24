// Ingeniería de Datos II — red logística Neo4j
// Ejecutar en Neo4j Browser por sentencias o con cypher-shell -f neo4j/03_neo4j.cypher
// No crea nodos ni recorridos de prueba; solo restricciones e índices.
CREATE CONSTRAINT punto_id_unico IF NOT EXISTS FOR (p:PuntoEntrega) REQUIRE p.punto_entrega_id IS UNIQUE;
CREATE CONSTRAINT ruta_id_unico IF NOT EXISTS FOR (r:Ruta) REQUIRE r.ruta_id IS UNIQUE;
CREATE INDEX punto_localidad IF NOT EXISTS FOR (p:PuntoEntrega) ON (p.localidad);
CREATE INDEX ruta_estado IF NOT EXISTS FOR (r:Ruta) ON (r.estado);
// Modelo acordado:
// (:PuntoEntrega {punto_entrega_id, nombre, latitud, longitud, localidad})
// -[:CONECTA {tramo_id, distancia_km, tiempo_estimado_min, habilitado}]->
// (:PuntoEntrega)
// (:Ruta {ruta_id, estado})-[:INCLUYE {orden}]->(:PuntoEntrega)
// Para tramos bidireccionales crear ambas relaciones dirigidas CONECTA.
// Cada relación CONECTA se identifica por tramo_id a nivel aplicativo.
// Idempotencia de datos de prueba: usar MERGE en los nodos y relación con clave tramo_id.
// EJEMPLO DE PRUEBA (cargar datos reales antes):
// MATCH (a:PuntoEntrega {punto_entrega_id:'P-1'}), (b:PuntoEntrega {punto_entrega_id:'P-2'})
// MERGE (a)-[t:CONECTA {tramo_id:'T-1-2'}]->(b)
// SET t.distancia_km=3.8, t.tiempo_estimado_min=8, t.habilitado=true;
// Consulta de conexiones habilitadas a un punto:
// MATCH (a:PuntoEntrega {punto_entrega_id:'P-1'})-[c:CONECTA]->(b:PuntoEntrega)
// WHERE c.habilitado = true
// RETURN b.punto_entrega_id, c.distancia_km, c.tiempo_estimado_min;
// Para CU-07 usar búsqueda de caminos con filtro por habilitación y validación de costos
// mediante Cypher/GDS según la edición instalada (pendiente de implementar y probar).
