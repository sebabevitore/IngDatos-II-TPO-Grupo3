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

-- CU-03 y CU-08: Registro histórico de alertas por viaje y día (análisis temporal y trazabilidad).
CREATE TABLE IF NOT EXISTS alertas_por_viaje_dia (
  viaje_id text,
  dia date,
  fecha_hora timestamp,
  alerta_id text,
  vehiculo_patente text,
  tipo text,
  descripcion text,
  latitud double,
  longitud double,
  valor_observado double,
  umbral double,
  clave_deduplicacion text,
  resuelta boolean,
  fecha_resolucion timestamp,
  contexto text,
  PRIMARY KEY ((viaje_id, dia), fecha_hora, alerta_id)
) WITH CLUSTERING ORDER BY (fecha_hora ASC, alerta_id ASC);

-- CU-03: Histórico de alertas por vehículo y día (inclusive sin viaje activo).
CREATE TABLE IF NOT EXISTS alertas_por_vehiculo_dia (
  vehiculo_patente text,
  dia date,
  fecha_hora timestamp,
  alerta_id text,
  viaje_id text,
  tipo text,
  descripcion text,
  latitud double,
  longitud double,
  valor_observado double,
  umbral double,
  clave_deduplicacion text,
  resuelta boolean,
  fecha_resolucion timestamp,
  contexto text,
  PRIMARY KEY ((vehiculo_patente, dia), fecha_hora, alerta_id)
) WITH CLUSTERING ORDER BY (fecha_hora ASC, alerta_id ASC);

-- CU-03: Espejo durable de anomalías abiertas (fuente de la verdad para reconciliar con Redis).
CREATE TABLE IF NOT EXISTS alertas_abiertas_por_vehiculo (
  vehiculo_patente text,
  tipo text,
  alerta_id text,
  viaje_id text,
  dia date,
  fecha_hora timestamp,
  PRIMARY KEY ((vehiculo_patente), tipo)
);

-- CU-03: Bitácora de pasos completados por operación (requisito obligatorio de la Sección 5).
CREATE TABLE IF NOT EXISTS alertas_log_pasos (
  alerta_id text,
  ts timestamp,
  paso text,
  estado text,
  detalle text,
  PRIMARY KEY ((alerta_id), ts, paso)
) WITH default_time_to_live = 604800;

-- CU-06: Histórico inmutable de confirmaciones de entrega (Proof of Delivery / Trazabilidad).
CREATE TABLE IF NOT EXISTS confirmaciones_entrega_por_viaje_dia (
  viaje_id text,
  dia date,
  fecha_hora timestamp,
  paquete_codigo text,
  vehiculo_patente text,
  receptor_nombre text,
  receptor_dni text,
  receptor_vinculo text,
  latitud double,
  longitud double,
  id_evento uuid,
  PRIMARY KEY ((viaje_id, dia), fecha_hora, paquete_codigo)
) WITH CLUSTERING ORDER BY (fecha_hora ASC, paquete_codigo ASC);

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

CREATE TABLE IF NOT EXISTS logistica_flota.tiempos_tramo_historico (
  tramo_id text,
  fecha_hora timestamp,
  viaje_id text,
  duracion_minutos double,
  PRIMARY KEY (tramo_id, fecha_hora)
) WITH CLUSTERING ORDER BY (fecha_hora DESC);


-- Consultas de ejemplo:
-- SELECT * FROM telemetria_por_viaje_dia
-- WHERE viaje_id = 'VIAJE-1001' AND dia = '2026-10-25'
-- AND fecha_hora >= '2026-10-25T09:00:00Z'
-- AND fecha_hora < '2026-10-25T10:00:00Z';
-- SELECT * FROM telemetria_por_vehiculo_dia
-- WHERE vehiculo_patente = 'AB123CD' AND dia = '2026-10-25';
-- SELECT * FROM alertas_por_vehiculo_dia
-- WHERE vehiculo_patente = 'AB123CD' AND dia = '2026-10-25';
-- SELECT * FROM confirmaciones_entrega_por_viaje_dia
-- WHERE viaje_id = 'VIAJE-1001' AND dia = '2026-10-30';
