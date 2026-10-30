"""
Repositorio Redis para el Caso de Uso 6 (Confirmación de entrega).
Responsable del lock atómico de no-duplicación por paquete y la actualización
de contadores en tiempo real del viaje.
"""

from typing import Tuple, Dict, Any, Optional
import redis

# Script Lua para compare-and-delete (liberar lock solo si somos dueños del token)
SCRIPT_LIBERAR_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""

# Script Lua para verificación e intento de bloqueo atómico de entrega
SCRIPT_BLOQUEAR_ENTREGA = """
local clave_paquete = KEYS[1]
local clave_lock = KEYS[2]
local token_saga = ARGV[1]
local ttl = tonumber(ARGV[2])

local estado = redis.call('HGET', clave_paquete, 'estado')
if estado == 'ENTREGADO' then
    return -1
end

local res = redis.call('SET', clave_lock, token_saga, 'NX', 'EX', ttl)
if res then
    return 1
else
    return 0
end
"""


def bloquear_entrega_paquete_redis(
    cliente: redis.Redis,
    paquete_codigo: str,
    token_saga: str,
    ttl_segundos: int = 30
) -> Tuple[bool, str]:
    """
    Adquiere un lock atómico temporal sobre el paquete (SET NX EX)
    comprobando en el mismo ciclo atómico que el paquete no haya sido ya marcado ENTREGADO.
    Evita que dos llamadas concurrentes o reintentos dupliquen la confirmación.
    """
    paq = paquete_codigo.strip()
    clave_paquete = f"paquete:{paq}:estado"
    clave_lock = f"lock:entrega:paquete:{paq}"

    resultado = cliente.eval(
        SCRIPT_BLOQUEAR_ENTREGA,
        2,
        clave_paquete,
        clave_lock,
        token_saga,
        ttl_segundos
    )

    if resultado == -1:
        return False, f"El paquete {paq} ya fue entregado previamente (idempotencia)"
    elif resultado == 0:
        return False, f"El paquete {paq} ya está en proceso de entrega simultánea"

    return True, "OK"


def liberar_bloqueo_entrega_redis(
    cliente: redis.Redis,
    paquete_codigo: str,
    token_saga: str
) -> bool:
    """
    Acción de compensación (Rollback): Libera el lock temporal si la operación
    falla posteriormente en Cassandra o MongoDB.
    """
    clave_lock = f"lock:entrega:paquete:{paquete_codigo.strip()}"
    resultado = cliente.eval(SCRIPT_LIBERAR_LOCK, 1, clave_lock, token_saga)
    return resultado == 1


def consolidar_entrega_redis(
    cliente: redis.Redis,
    viaje_id: str,
    paquete_codigo: str,
    token_saga: str
):
    """
    Paso final en Redis:
    1. Incrementa el contador de entregas completadas del viaje.
    2. Actualiza el estado del paquete en caché a 'ENTREGADO'.
    3. Libera el lock temporal de entrega.
    """
    pipe = cliente.pipeline()

    # Contador operativo del viaje
    clave_progreso = f"viaje:{viaje_id.strip()}:progreso"
    pipe.hincrby(clave_progreso, "entregas_completadas", 1)

    # Estado rápido del paquete
    clave_paquete = f"paquete:{paquete_codigo.strip()}:estado"
    pipe.hset(clave_paquete, mapping={
        "estado": "ENTREGADO",
        "viaje_id": viaje_id
    })

    # Liberar lock de entrega
    clave_lock = f"lock:entrega:paquete:{paquete_codigo.strip()}"
    pipe.delete(clave_lock)

    pipe.execute()


def obtener_progreso_viaje_redis(cliente: redis.Redis, viaje_id: str) -> Dict[str, str]:
    """Recupera los contadores del viaje en memoria."""
    clave = f"viaje:{viaje_id.strip()}:progreso"
    return cliente.hgetall(clave)
