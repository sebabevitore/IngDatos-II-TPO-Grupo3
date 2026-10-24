# Redis — modelo de estado operativo (CU-01, CU-02, CU-03, CU-04, CU-05)

Redis es **un almacén sin esquema DDL**. Este documento define nombres, tipos, contratos de uso y comandos de prueba.
MongoDB mantiene las asignaciones confirmadas; Redis mantiene reservas transitorias.

| Clave | Tipo | Campos/valor | Política |
| --- | --- | --- | --- |
| `vehiculo:{patente}:estado` | Hash | `viaje_id`, `latitud`, `longitud`, `velocidad`, `estado`, `fecha_hora_ms` | Se actualiza solo si la medición es más reciente. Rehidratar desde Cassandra si se pierde. |
| `reserva:vehiculo:{patente}` | String | `operacion_id` | NX + PX temporal; liberar con comparación de token. |
| `reserva:conductor:{id}` | String | `operacion_id` | NX + PX temporal; liberar con comparación de token. |
| `alerta:activa:{patente}:{tipo}` | String | `episodio_id` | Se limpia al terminar el episodio; TTL supervisado. |

## Ejemplos manuales (redis-cli)

```redis
SET reserva:vehiculo:AB123CD OP-123 NX PX 30000
GET reserva:vehiculo:AB123CD
HGETALL vehiculo:AB123CD:estado
```

**IMPORTANTE:** Nunca liberar reservas con `DEL` sin comprobar primero quién es dueño. Usar `redis/05_release_if_owned.lua` como operación atómica. Adquirir dos reservas por separado **no** equivale a una transacción global: si falla la segunda, compensar la primera y persistir el estado de la operación en MongoDB. La disponibilidad definitiva y las ventanas horarias deben validarse en MongoDB de forma transaccional; un TTL no demuestra ausencia de solapamiento.

Para telemetría, `redis/06_update_if_newer.lua` impide que eventos atrasados reemplacen posiciones recientes. Cassandra es el histórico persistente para reconciliación.
