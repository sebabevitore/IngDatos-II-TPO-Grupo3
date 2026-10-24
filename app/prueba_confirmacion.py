
from uuid import uuid4

from app.conexiones import conectar_redis
from app.reservas import confirmar_recurso, liberar_recurso


def main():
    redis = conectar_redis()

    clave = f"reserva:vehiculo:TEST-{uuid4().hex[:8]}"
    token = str(uuid4())

    try:
        # 1. Crear una reserva temporal
        creado = redis.set(clave, token, nx=True, ex=300)
        assert creado is True
        assert redis.ttl(clave) > 0

        print("[OK] Reserva temporal creada")

        # 2. Intentar confirmar con un token incorrecto
        resultado_incorrecto = confirmar_recurso(
            redis, clave, "token-incorrecto"
        )

        assert resultado_incorrecto == 0
        assert redis.ttl(clave) > 0

        print("[OK] Token incorrecto rechazado")

        # 3. Confirmar con el token correcto
        confirmado = confirmar_recurso(redis, clave, token)

        assert confirmado == 1
        assert redis.ttl(clave) == -1

        print("[OK] Reserva confirmada correctamente")
        print("[OK] Reserva sin expiracion automatica")
        print("PRUEBA DE CONFIRMACION EXITOSA")

    finally:
        # Liberar solamente nuestra reserva de prueba
        liberar_recurso(redis, clave, token)
        redis.close()


if __name__ == "__main__":
    main()
