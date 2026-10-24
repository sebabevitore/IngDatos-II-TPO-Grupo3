
from uuid import uuid4

from app.conexiones import conectar_mongodb, conectar_redis
from app.coordinador_viajes import planificar_viaje


class RedisConFalla:
    """
    Utiliza Redis real, pero simula un rechazo
    al confirmar la reserva del conductor.
    """

    def __init__(self, cliente):
        self.cliente = cliente

    def set(self, *args, **kwargs):
        return self.cliente.set(*args, **kwargs)

    def eval(self, script, cantidad_claves, clave, token):
        if (
            "PERSIST" in script
            and clave.startswith("reserva:conductor:")
        ):
            return 0

        return self.cliente.eval(
            script, cantidad_claves, clave, token
        )


def main():
    mongo = conectar_mongodb()
    redis = conectar_redis()

    sufijo = uuid4().hex[:8]

    datos = {
        "id_ruta": f"R-TEST-{sufijo}",
        "id_vehiculo": f"V-TEST-{sufijo}",
        "id_conductor": f"C-TEST-{sufijo}",
        "paquetes": [f"P-TEST-{sufijo}"]
    }

    coleccion = mongo["logistica"]["viajes"]
    redis_con_falla = RedisConFalla(redis)

    clave_vehiculo = f"reserva:vehiculo:{datos['id_vehiculo']}"
    clave_conductor = f"reserva:conductor:{datos['id_conductor']}"

    try:
        exito, resultado = planificar_viaje(
            redis_con_falla, coleccion, datos
        )

        assert exito is False
        print("[OK] Se detecto la falla de confirmacion")

        viaje = coleccion.find_one({
            "id_vehiculo": datos["id_vehiculo"]
        })

        assert viaje is None
        print("[OK] Viaje eliminado de MongoDB")

        assert redis.get(clave_vehiculo) is None
        assert redis.get(clave_conductor) is None

        print("[OK] Ambas reservas liberadas de Redis")
        print("PRUEBA DE COMPENSACION DISTRIBUIDA EXITOSA")

    finally:
        redis.close()
        mongo.close()


if __name__ == "__main__":
    main()
