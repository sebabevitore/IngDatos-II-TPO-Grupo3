-- Script Lua para Claim atómico y deduplicación de anomalías en Redis.
-- KEYS[1] = alerta:activa:{patente}:{tipo}
-- ARGV[1] = alerta_id
-- ARGV[2] = viaje_id
-- ARGV[3] = dia (YYYY-MM-DD)
-- ARGV[4] = fecha_hora_iso
-- ARGV[5] = ttl_pending_segundos (ej: 30)
-- ARGV[6] = ttl_activo_segundos (ej: 120)

local exists = redis.call('EXISTS', KEYS[1])

if exists == 0 then
    -- No existe: creamos el claim en estado PENDING con TTL corto
    redis.call('HSET', KEYS[1],
        'alerta_id', ARGV[1],
        'estado', 'PENDING',
        'viaje_id', ARGV[2],
        'dia', ARGV[3],
        'fecha_hora', ARGV[4],
        'primera_vez', ARGV[4],
        'ultima_vez', ARGV[4],
        'cantidad', 1
    )
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
    -- Retorna 1: Claim exitoso. El orquestador debe persistir en Cassandra.
    return 1
else
    -- Ya existe una anomalía activa o en progreso (anomalía sostenida)
    -- Extendemos el TTL para que no expire mientras siga la condición anómala
    redis.call('HSET', KEYS[1], 'ultima_vez', ARGV[4])
    redis.call('HINCRBY', KEYS[1], 'cantidad', 1)
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[6]))
    -- Retorna 0: Deduplicado. No escribir nuevo evento en Cassandra ni alertar.
    return 0
end

