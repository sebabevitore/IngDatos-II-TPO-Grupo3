-- KEYS[1] = clave reserva; ARGV[1] = operacion_id/token del propietario
-- Retorna 1 si se eliminó, 0 si no es propietario o no existe.
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
