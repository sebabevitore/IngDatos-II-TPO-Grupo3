
from app.viajes import validar_viaje
from app.reservas import (
    reservar_recursos,
    liberar_recurso,
    confirmar_recurso
)
from app.repositorio_viajes import (
    registrar_viaje,
    eliminar_viaje
)


def planificar_viaje(cliente_redis, coleccion_mongo, datos):
    valido, mensaje = validar_viaje(datos)

    if not valido:
        return False, mensaje

    # Reservar recursos temporalmente
    reservado, resultado = reservar_recursos(
        cliente_redis,
        datos["id_vehiculo"],
        datos["id_conductor"]
    )

    if not reservado:
        return False, resultado

    token = resultado

    clave_vehiculo = f"reserva:vehiculo:{datos['id_vehiculo']}"
    clave_conductor = f"reserva:conductor:{datos['id_conductor']}"

    id_viaje = None

    try:
        # Registrar el viaje en MongoDB
        id_viaje = registrar_viaje(
            coleccion_mongo,
            datos,
            id_operacion=token
        )

        # Confirmar ambas reservas en Redis
        confirmado_vehiculo = confirmar_recurso(
            cliente_redis, clave_vehiculo, token
        )

        confirmado_conductor = confirmar_recurso(
            cliente_redis, clave_conductor, token
        )

        if confirmado_vehiculo != 1 or confirmado_conductor != 1:
            raise RuntimeError(
                "No se pudieron confirmar ambas reservas"
            )

        return True, {
            "id_viaje": id_viaje,
            "estado": "PLANIFICADO"
        }

    except Exception as error:
        # Compensacion en MongoDB si se registro el viaje
        if id_viaje is not None:
            eliminar_viaje(coleccion_mongo, id_viaje)

        # Liberar solamente las reservas propias
        liberar_recurso(
            cliente_redis, clave_vehiculo, token
        )
        liberar_recurso(
            cliente_redis, clave_conductor, token
        )

        return False, f"Operacion compensada: {error}"
