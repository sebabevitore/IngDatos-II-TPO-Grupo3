-- KEYS[1] = vehiculo:{patente}:estado
-- ARGV[1] fecha_hora_ms (entero Unix ms), [2] viaje_id, [3] latitud, [4] longitud,
-- [5] velocidad, [6] estado
-- Retorna 1 si actualizó, 0 si descartó evento viejo o repetido.
local last = redis.call('HGET', KEYS[1], 'fecha_hora_ms')
local incoming = tonumber(ARGV[1])
if not incoming then return redis.error_reply('fecha_hora_ms invalida') end
if last and incoming <= tonumber(last) then return 0 end
redis.call('HSET', KEYS[1],
  'fecha_hora_ms', ARGV[1], 'viaje_id', ARGV[2],
  'latitud', ARGV[3], 'longitud', ARGV[4],
  'velocidad', ARGV[5], 'estado', ARGV[6])
return 1
