
from uuid import uuid4


# Libera una reserva solo si pertenece a nuestra operacion.
LIBERAR_RESERVA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


def liberar_recurso(cliente_redis, clave, token):
    return cliente_redis.eval(
        LIBERAR_RESERVA,
        1,
        clave,
        token
    )


def reservar_recursos(cliente_redis, id_vehiculo, id_conductor):
    """
    Reserva temporalmente un vehiculo y un conductor.

    Devuelve:
        (True, token) si ambas reservas se realizan.
        (False, mensaje) si algun recurso esta ocupado.
    """

    token = str(uuid4())

    clave_vehiculo = f"reserva:vehiculo:{id_vehiculo}"
    clave_conductor = f"reserva:conductor:{id_conductor}"

    vehiculo_reservado = cliente_redis.set(
        clave_vehiculo,
        token,
        nx=True,
        ex=300
    )

    if not vehiculo_reservado:
        return False, "El vehiculo ya esta reservado"

    try:
        conductor_reservado = cliente_redis.set(
            clave_conductor,
            token,
            nx=True,
            ex=300
        )
    except Exception:
        liberar_recurso(cliente_redis, clave_vehiculo, token)
        raise

    if not conductor_reservado:
        liberar_recurso(cliente_redis, clave_vehiculo, token)
        return False, "El conductor ya esta reservado"

    return True, token

CONFIRMAR_RESERVA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PERSIST', KEYS[1])
else
    return 0
end
"""


def confirmar_recurso(cliente_redis, clave, token):
    """
    Confirma una reserva temporal quitando su expiracion,
    solamente si pertenece a nuestra operacion.
    """
    return cliente_redis.eval(
        CONFIRMAR_RESERVA,
        1,
        clave,
        token
    )
