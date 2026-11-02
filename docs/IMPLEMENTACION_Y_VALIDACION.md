# Correcciones y validación de la Etapa 2

Esta nota describe la rama `codex/correcciones-consistencia-tpo` y reemplaza el diagnóstico de pendientes para los flujos corregidos. El DER no se modificó. Las nuevas colecciones y marcas técnicas son mecanismos de coordinación de la aplicación.

## Cambios que deben reflejarse en el informe

1. **Evolución y planificación.** Los viajes nuevos incluyen paradas con horarios y usuario coordinador existente. Las asignaciones registran al responsable. Los intervalos se validan bajo bloqueo durable; los viajes no superpuestos se permiten. Una distribución uniforme del intervalo es el plan de referencia cuando no se proporcionan horarios explícitos.
2. **Consistencia.** `app/operaciones.py` registra entrada, identidad, propietario, pasos iniciados/completados y fotografías anteriores. Los bloqueos MongoDB no expiran al perder Redis. Una operación interrumpida se compensa con `app/recuperar_operaciones.py` cuando su proceso local terminó. Las compensaciones fallidas retienen los recursos y se pueden reintentar. No se promete una transacción global ni recuperación automática entre hosts.
3. **CU05 y CU06.** Las fallas finales Redis provocan compensación; no se devuelve éxito comercial con métricas pendientes. Una vez registrado el commit global en la bitácora, no se revierte por pérdida de ACK o error al limpiar bloqueos: se preserva el resultado y se limpia posteriormente.
4. **CU06.** El viaje MongoDB conserva completadas, pendientes y demora acumulada. La demora se suma una sola vez por parada completada, al entregar todos sus paquetes. Redis recibe valores absolutos. La prueba de idempotencia también contempla perder la clave Redis del paquete.
5. **CU03.** Se leen ventanas temporales de varios días sin un límite fijo de 15 muestras. La parada programada usa horario y proximidad al punto. Cassandra mantiene la identidad de la alerta abierta aunque se pierda Redis; una lectura normal la cierra. Una escritura histórica parcial se compensa usando la intención durable; una alerta ya persistida con confirmación/aviso pendiente se completa hacia adelante.
6. **CU04.** Se calcula avance sobre segmentos, duración restante histórica o planificada y tiempo a velocidad actual, con ponderación explícita 50/50. Sin historia, se prioriza la duración entre horarios de las paradas; el tiempo del grafo es el respaldo si faltan. Se informa horario previsto, llegada y demora estimada. El desvío usa distancia al segmento; las posiciones desactualizadas se rechazan. Es una aproximación entre puntos, sin servicio externo de tráfico o cartografía vial.
7. **Fuentes oficiales.** Alertas operativas en Cassandra; negocio y métricas en MongoDB; reservas/proyecciones en Redis; conectividad en Neo4j. La colección MongoDB `alertas` se conserva como compatibilidad del seed, no como espejo actualizado del flujo operativo. No hay edición genérica de rutas/maestros ni sincronización de cambios manuales fuera de la aplicación.

## Secuencias de escritura

### CU01

MongoDB registra operación -> bloquea recursos -> valida intervalo/paquetes/ruta -> Redis reserva -> Neo4j vincula viaje -> MongoDB registra viaje/asignaciones/estados -> Redis confirma -> MongoDB marca COMPLETADO y libera bloqueos.

Ante una falla anterior al commit: restaurar fotografías MongoDB, eliminar viaje Neo4j y liberar reservas propias Redis. Si alguna compensación falla, mantener COMPENSACION_PENDIENTE y recursos bloqueados.

### CU05

MongoDB registra operación y bloquea viaje/recursos/paquetes -> Redis reserva reemplazo -> Neo4j vincula rescate -> MongoDB interrumpe tramos y crea rescate/asignaciones -> Redis consolida estados -> MongoDB confirma operación.

Ante falla: restaurar todos los documentos propios, eliminar el rescate del grafo/restablecer el viaje original y restaurar solo campos operativos Redis. No borrar coordenadas GPS posteriores ni liberar reservas ajenas.

### CU06

MongoDB registra intención, fecha y clave Cassandra; bloquea paquete/viaje -> Redis reserva -> Cassandra escribe comprobante -> MongoDB marca entrega, cierra asignación/parada y recalcula métricas -> Redis proyecta métricas -> MongoDB confirma operación.

Ante falla anterior al commit: eliminar comprobante por clave completa, restaurar documentos propios y restaurar campos Redis. Las intenciones permiten compensar incluso si el proceso cae tras una escritura y antes de recibir el ACK.

### CU03

MongoDB registra intención y bloquea vehículo/tipo de anomalía -> Redis reclama -> Cassandra escribe proyecciones y alerta abierta -> Redis activa -> consola emite aviso -> MongoDB confirma operación.

Una escritura histórica incompleta se compensa. Una escritura persistida con confirmación/aviso pendiente se completa hacia adelante. La emisión en consola tiene semántica al menos una vez: podría repetirse tras una caída.

## Evidencia ejecutada

- `evidencias/validacion-entrega/resultado.json`: comandos, códigos de salida, rama, commit base y SHA-256 de los archivos probados. Sus logs contienen reglas, integración y los menús CU01 a CU07.
- `evidencias/correcciones/`: verificaciones sobre motores por prueba, incluidas caídas de proceso, falla de compensación, ACK perdido, Redis final y planificación por intervalos.
- `resultados_menus/`: resultados de cada demostración, incluida la simulación de 50 vehículos/250 mediciones. CU08 se contrasta en planificación, rescate, entrega y operación pendiente.
- `evidencias/cu08.log`: prueba específica de trazabilidad histórica, código vacío y paquete inexistente.
- `evidencias/seed-historico.json`: verificación de las 50.000 mediciones y sus proyecciones persistentes contra el manifiesto original, sin exigir que el estado Redis actual coincida con su posición antigua.

La validación estricta `cargar_datos --solo-validar` compara también Redis con el snapshot inicial. Después de simular GPS es esperado que falle por posición distinta; el intento queda registrado en `evidencias/validacion-seed/resultado.json`. No se restauró una posición antigua para forzar una aprobación. La simulación verifica la nueva posición actual y su persistencia.

## Reproducción

```bash
python -m app.verificar_correcciones --integracion
python -m app.verificar_seed_historico
python -m app.test_cu08
```

La ejecución conserva datos existentes y usa fixtures exclusivas. No se hizo una limpieza global, no se vaciaron volúmenes y no se volvió a cargar el seed sobre entidades modificadas.

## Límites del entorno

La recuperación protege el laboratorio de un solo host y es manual; no roba un proceso vivo. La disponibilidad de MongoDB es necesaria para coordinar. Los módulos históricos `repositorio_entrega_mongo.py`, `repositorio_reasignacion_mongo.py` y auxiliares Redis previos se mantienen para compatibilidad de scripts; la aplicación usa los orquestadores públicos y `flujos_durables.py`. No deben llamarse esos auxiliares históricos como sustituto del protocolo completo. No se implementa aislamiento distribuido general para consultas arbitrarias fuera de esos flujos.

La validación final incluye 7 pruebas unitarias, 11 pruebas de integración (con subcasos), 27 escenarios de menús y la prueba específica CU08. Las rutas y huellas de cada ejecución se conservan para distinguir resultados anteriores de la versión final.
