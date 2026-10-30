import os
import sys

# Permite ejecutar directamente el archivo con el botón de Play del editor
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from uuid import uuid4

from app.conexiones import (
    conectar_mongodb,
    conectar_redis,
    conectar_neo4j
)
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
    neo4j_driver = conectar_neo4j()

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
            redis_con_falla,
            coleccion,
            datos,
            driver_neo4j=neo4j_driver
        )

        assert exito is False
        print("[OK] Se detecto la falla de confirmacion en Redis")

        # 1. Comprobar rollback en MongoDB
        viaje = coleccion.find_one({
            "id_vehiculo": datos["id_vehiculo"]
        })
        assert viaje is None
        print("[OK] Documento de viaje eliminado de MongoDB")

        # 2. Comprobar rollback en Neo4j
        with neo4j_driver.session() as sesion:
            res = sesion.run(
                "MATCH (v:Viaje)-[:ASIGNADO_A]->(r:Ruta {ruta_id: $id_ruta}) RETURN count(v) AS cnt",
                id_ruta=datos["id_ruta"]
            )
            count = res.single()["cnt"]
            assert count == 0
            print("[OK] Nodo de viaje eliminado de Neo4j")

        # 3. Comprobar rollback en Redis
        assert redis.get(clave_vehiculo) is None
        assert redis.get(clave_conductor) is None
        print("[OK] Ambas reservas temporales liberadas de Redis")

        print("PRUEBA DE COMPENSACION DISTRIBUIDA CU-01 EXITOSA (MongoDB + Neo4j + Redis)")

    finally:
        redis.close()
        mongo.close()
        neo4j_driver.close()


if __name__ == "__main__":
    main()
