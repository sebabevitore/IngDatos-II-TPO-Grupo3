-- Script Lua para liberación/rollback seguro de anomalía en Redis (Compare-and-Delete).
-- Borra la clave solo si el alerta_id coincide con el esperado, evitando borrar
-- accidentalmente una anomalía posterior creada por otro proceso.
-- KEYS[1] = alerta:activa:{patente}:{tipo}
-- ARGV[1] = alerta_id esperado

local actual_id = redis.call('HGET', KEYS[1], 'alerta_id')

if actual_id == ARGV[1] then
    redis.call('DEL', KEYS[1])
    return 1 -- Eliminado con éxito
else
    return 0 -- No coincide o no existe; no se borró
end

