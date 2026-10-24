# Ingeniería de Datos II — TPO Etapa 2
## Sistema de logística y tracking de flota

**Cuatro motores elegidos:** MongoDB (negocio), Cassandra (telemetría histórica), Redis (estado operativo y reservas), Neo4j (red y caminos logísticos).

## Contenido
- `mongodb/01_mongodb.js`: creación de 11 colecciones e índices.
- `cassandra/02_cassandra.cql`: keyspace local y cuatro tablas orientadas a consultas.
- `neo4j/03_neo4j.cypher`: restricciones, índices y contrato del grafo.
- `redis/04_redis.md`: claves y estructuras de datos.
- `redis/05_release_if_owned.lua`: libera una reserva solo si coincide el token propietario.
- `redis/06_update_if_newer.lua`: actualización monotónica del último estado del vehículo.
- `.github/workflows/validacion-basica.yml`: verifica estructura en cada push/PR; **no** verifica funcionamiento de motores.

## Crear un repositorio compartido
1. Un integrante crea un repositorio **privado** en GitHub (ej. `tpo-logistica-id2`).
2. Invita a sus compañeros en Settings > Collaborators / Manage access.
3. Desde la carpeta raíz del proyecto ejecuta:
```bash
git init
git add .
git commit -m "Agregar esquemas iniciales de los cuatro motores"
git branch -M main
git remote add origin https://github.com/USUARIO/tpo-logistica-id2.git
git push -u origin main
```
4. Cada integrante clona el repositorio, crea una rama `feature/...`, sube sus cambios y abre un Pull Request.

## Ejecución (requiere motores instalados y corriendo)
- `mongosh mongodb/01_mongodb.js`
- `cqlsh -f cassandra/02_cassandra.cql` (Cassandra local; replicación RF=1 de laboratorio)
- `cypher-shell -u neo4j -p TU_PASSWORD -f neo4j/03_neo4j.cypher`
- Para Redis: `redis-cli --eval redis/05_release_if_owned.lua reserva:vehiculo:AB123CD , OP-123` (ejemplo de liberación; primero debe haberse reservado). Para actualización: `redis-cli --eval redis/06_update_if_newer.lua vehiculo:AB123CD:estado , 1792936800000 VIAJE-1001 -34.6 -58.4 65 EN_RUTA`.

## Estado y trabajo pendiente
Los scripts son **diseño inicial**. No fueron ejecutados contra los cuatro motores. No hay todavía aplicación Python, CI con pruebas reales, datos de 50.000 mediciones ni rollback completo. La semántica de Neo4j CU-07 se debe implementar y probar.

Antes de considerar aprobado el modelado: acordar la fuente oficial de alertas (MongoDB), evitar solapamientos de vehículos/conductores mediante validaciones transaccionales persistentes (no solo Redis), crear mecanismos de recuperación para escrituras Cassandra/Redis, y diseñar las consultas multi-día en Cassandra. No colocar contraseñas ni archivos `.env` en GitHub.
