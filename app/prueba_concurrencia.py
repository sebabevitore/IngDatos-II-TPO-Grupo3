
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.conexiones import conectar_redis
from app.reservas import reservar_recursos, liberar_recurso


def main():
    redis = conectar_redis()

    sufijo = uuid4().hex[:8]
    vehiculo = f"V-CONC-{sufijo}"

    conductores = [
        f"C-CONC-{sufijo}-1",
        f"C-CONC-{sufijo}-2"
    ]

    def intentar_reserva(conductor):
        return reservar_recursos(redis, vehiculo, conductor)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(
                executor.map(intentar_reserva, conductores)
            )

        exitosas = sum(1 for exito, _ in resultados if exito)

        assert exitosas == 1, (
            f"Se esperaba una reserva exitosa, "
            f"pero hubo {exitosas}"
        )

        print("[OK] Se ejecutaron dos reservas concurrentes")
        print("[OK] Solo una reserva fue exitosa")
        print("[OK] Redis impidio duplicar el vehiculo")
        print("PRUEBA DE CONCURRENCIA EXITOSA")

    finally:
        # Liberar solamente las reservas que esta prueba obtuvo
        for conductor, (exito, token) in zip(
            conductores,
            locals().get("resultados", [])
        ):
            if exito:
                liberar_recurso(
                    redis,
                    f"reserva:vehiculo:{vehiculo}",
                    token
                )
                liberar_recurso(
                    redis,
                    f"reserva:conductor:{conductor}",
                    token
                )

        redis.close()


if __name__ == "__main__":
    main()
