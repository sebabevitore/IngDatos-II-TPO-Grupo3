import os
import sys

# Permite ejecutar directamente el archivo con el botón de Play del editor
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from uuid import uuid4

from app.conexiones import conectar_redis, conectar_neo4j
from app.coordinador_viajes import planificar_viaje
from app.repositorio_rutas_neo4j import consultar_viaje_neo4j


class MongoConFalla:
    """
    Simula un error al registrar el viaje en MongoDB.
    Redis y Neo4j, en cambio, son completamente reales.
    """

    def insert_one(self, documento):
        raise RuntimeError("Falla simulada en MongoDB")


def main():
    redis = conectar_redis()
    neo4j_driver = conectar_neo4j()

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
            datos,
            driver_neo4j=neo4j_driver
        )

        assert exito is False
        print("[OK] Se detecto la falla de MongoDB")

        # Verificar compensación en Redis
        assert redis.get(clave_vehiculo) is None
        print("[OK] Reserva del vehiculo liberada en Redis")

        assert redis.get(clave_conductor) is None
        print("[OK] Reserva del conductor liberada en Redis")

        # Verificar compensación en Neo4j (el nodo debió ser eliminado)
        # Consultamos si quedó algún viaje vinculado a esta ruta de prueba
        with neo4j_driver.session() as sesion:
            res = sesion.run(
                "MATCH (v:Viaje)-[:ASIGNADO_A]->(r:Ruta {ruta_id: $id_ruta}) RETURN count(v) AS cnt",
                id_ruta=datos["id_ruta"]
            )
            count = res.single()["cnt"]
            assert count == 0, "El viaje no fue eliminado de Neo4j durante el rollback"
            print("[OK] Nodo y relaciones eliminados de Neo4j (Rollback exitoso)")

        print("PRUEBA DE COMPENSACION DISTRIBUIDA CU-01 EXITOSA (Redis + Neo4j + Mongo)")

    finally:
        redis.close()
        neo4j_driver.close()


if __name__ == "__main__":
    main()
