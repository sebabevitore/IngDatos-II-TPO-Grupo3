
-- KEYS[1] = vehiculo:{patente}:estado
-- ARGV[1] = fecha_hora_ms (Unix en milisegundos)
-- ARGV[2] = viaje_id
-- ARGV[3] = latitud
-- ARGV[4] = longitud
-- ARGV[5] = velocidad
-- ARGV[6] = estado

local incoming = tonumber(ARGV[1])

if not incoming then
    return redis.error_reply('fecha_hora_ms invalida')
end

local last = redis.call('HGET', KEYS[1], 'fecha_hora_ms')
local last_number = nil

if last then
    last_number = tonumber(last)

    if not last_number then
        return redis.error_reply('fecha_hora_ms almacenada invalida')
    end

    -- No sobrescribir con una medición antigua o repetida.
    if incoming <= last_number then
        return 0
    end
end

-- Guardar la medición más reciente.
redis.call(
    'HSET',
    KEYS[1],
    'fecha_hora_ms', ARGV[1],
    'viaje_id', ARGV[2],
    'latitud', ARGV[3],
    'longitud', ARGV[4],
    'velocidad', ARGV[5],
    'estado', ARGV[6]
)

return 1
