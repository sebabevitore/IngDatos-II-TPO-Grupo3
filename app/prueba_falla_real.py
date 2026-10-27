
from uuid import uuid4

from app.conexiones import conectar_redis
from app.coordinador_viajes import planificar_viaje


class MongoConFalla:
    """
    Simula un error al registrar el viaje.
    Redis, en cambio, es completamente real.
    """

    def insert_one(self, documento):
        raise RuntimeError("Falla simulada en MongoDB")


def main():
    redis = conectar_redis()

    sufijo = uuid4().hex[:8]

    datos = {
        "id_ruta": f"R-TEST-{sufijo}",
        "id_vehiculo": f"V-TEST-{sufijo}",
        "id_conductor": f"C-TEST-{sufijo}",
        "paquetes": [f"P-TEST-{sufijo}"]
    }

    clave_vehiculo = f"reserva:vehiculo:{datos['id_vehiculo']}"
    clave_conductor = f"reserva:conductor:{datos['id_conductor']}"

    try:
        exito, resultado = planificar_viaje(
            redis,
            MongoConFalla(),
            datos
        )

        assert exito is False
        print("[OK] Se detecto la falla de MongoDB")

        assert redis.get(clave_vehiculo) is None
        print("[OK] Reserva del vehiculo liberada")

        assert redis.get(clave_conductor) is None
        print("[OK] Reserva del conductor liberada")

        print("PRUEBA DE COMPENSACION EXITOSA")

    finally:
        redis.close()


if __name__ == "__main__":
    main()
