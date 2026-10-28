-- Ingeniería de Datos II — TPO Etapa 2
-- Ejecutar con cqlsh. Diseño orientado a consultas por viaje/vehículo y fecha.
CREATE KEYSPACE IF NOT EXISTS logistica_flota
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
-- SimpleStrategy RF=1 es SOLO para laboratorio local; revisar para producción/Astra DB.
USE logistica_flota;

-- CU-02 y CU-08: telemetría por viaje y día, orden temporal.
CREATE TABLE IF NOT EXISTS telemetria_por_viaje_dia (
  viaje_id text,
  dia date,
  fecha_hora timestamp,
  id_evento uuid,
  vehiculo_patente text,
  latitud double,
  longitud double,
  velocidad double,
  estado_vehiculo text,
  PRIMARY KEY ((viaje_id, dia), fecha_hora, id_evento)
) WITH CLUSTERING ORDER BY (fecha_hora ASC, id_evento ASC);

-- CU-02: consulta histórica puntual por vehículo y día, inclusive sin viaje activo.
-- Es una tabla desnormalizada deliberadamente: el proceso de ingesta escribe en ambas.
CREATE TABLE IF NOT EXISTS telemetria_por_vehiculo_dia (
  vehiculo_patente text,
  dia date,
  fecha_hora timestamp,
  id_evento uuid,
  viaje_id text,
  latitud double,
  longitud double,
  velocidad double,
  estado_vehiculo text,
  PRIMARY KEY ((vehiculo_patente, dia), fecha_hora, id_evento)
) WITH CLUSTERING ORDER BY (fecha_hora ASC, id_evento ASC);

-- Registro histórico de alertas para análisis temporal: fuente principal de alertas en MongoDB.
CREATE TABLE IF NOT EXISTS alertas_por_viaje_dia (
  viaje_id text,
  dia date,
  fecha_hora timestamp,
  alerta_id text,
  vehiculo_patente text,
  tipo text,
  descripcion text,
  PRIMARY KEY ((viaje_id, dia), fecha_hora, alerta_id)
) WITH CLUSTERING ORDER BY (fecha_hora ASC, alerta_id ASC);

-- Tiempos históricos precalculados por tramo para ETA (CU-04).
-- Este modelo requiere que la aplicación complete estas filas a partir de viajes concluidos.
CREATE TABLE IF NOT EXISTS tiempos_tramo_por_mes (
  tramo_id text,
  mes text,
  fecha_fin timestamp,
  viaje_id text,
  duracion_segundos int,
  PRIMARY KEY ((tramo_id, mes), fecha_fin, viaje_id)
) WITH CLUSTERING ORDER BY (fecha_fin DESC, viaje_id ASC);

-- Consultas de ejemplo: reemplazar IDs y fechas por valores de la carga de prueba.
-- SELECT * FROM telemetria_por_viaje_dia
-- WHERE viaje_id = 'VIAJE-1001' AND dia = '2026-10-25'py -0p
-- AND fecha_hora >= '2026-10-25T09:00:00Z'
-- AND fecha_hora < '2026-10-25T10:00:00Z';
-- SELECT * FROM telemetria_por_vehiculo_dia
-- WHERE vehiculo_patente = 'AB123CD' AND dia = '2026-10-25';
