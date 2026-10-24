
from uuid import uuid4

from app.conexiones import conectar_mongodb, conectar_redis
from app.coordinador_viajes import planificar_viaje
from app.reservas import liberar_recurso


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
    id_viaje = None
    token = None

    try:
        exito, resultado = planificar_viaje(
            redis, coleccion, datos
        )

        assert exito, f"Fallo la planificacion: {resultado}"

        id_viaje = resultado["id_viaje"]

        viaje = coleccion.find_one({"_id": id_viaje})
        assert viaje is not None
        assert viaje["estado"] == "PLANIFICADO"

        token = viaje["id_operacion"]

        clave_vehiculo = f"reserva:vehiculo:{datos['id_vehiculo']}"
        clave_conductor = f"reserva:conductor:{datos['id_conductor']}"

        assert redis.get(clave_vehiculo) == token
        assert redis.get(clave_conductor) == token

        print("[OK] Viaje registrado en MongoDB")
        print("[OK] Vehiculo reservado en Redis")
        print("[OK] Conductor reservado en Redis")
        print("PRUEBA REAL CU-01 EXITOSA")

    finally:
        # Limpiar los datos temporales de esta prueba
        if id_viaje is not None:
            coleccion.delete_one({"_id": id_viaje})

        if token is not None:
            liberar_recurso(
                redis,
                f"reserva:vehiculo:{datos['id_vehiculo']}",
                token
            )
            liberar_recurso(
                redis,
                f"reserva:conductor:{datos['id_conductor']}",
                token
            )

        redis.close()
        mongo.close()


if __name__ == "__main__":
    main()
