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
from app.reservas import liberar_recurso
from app.repositorio_rutas_neo4j import (
    consultar_viaje_neo4j,
    compensar_viaje_neo4j
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
    id_viaje = None
    token = None

    try:
        exito, resultado = planificar_viaje(
            redis,
            coleccion,
            datos,
            driver_neo4j=neo4j_driver
        )

        assert exito, f"Fallo la planificacion: {resultado}"

        id_viaje = resultado["id_viaje"]

        # 1. Verificación en MongoDB
        viaje = coleccion.find_one({"_id": id_viaje})
        assert viaje is not None
        assert viaje["estado"] == "PLANIFICADO"
        token = viaje["id_operacion"]

        # 2. Verificación en Redis
        clave_vehiculo = f"reserva:vehiculo:{datos['id_vehiculo']}"
        clave_conductor = f"reserva:conductor:{datos['id_conductor']}"

        assert redis.get(clave_vehiculo) == token
        assert redis.get(clave_conductor) == token

        # 3. Verificación en Neo4j (Grafo de la red logística)
        viaje_grafo = consultar_viaje_neo4j(neo4j_driver, id_viaje)
        assert viaje_grafo is not None, "El viaje no fue registrado en el grafo de Neo4j"
        assert viaje_grafo["estado"] == "PLANIFICADO"
        assert viaje_grafo["id_ruta"] == datos["id_ruta"]

        print("[OK] Vehiculo y conductor reservados en Redis")
        print("[OK] Recorrido y viaje vinculados en Neo4j")
        print("[OK] Documento de viaje registrado en MongoDB")
        print("PRUEBA REAL CU-01 EXITOSA (MongoDB + Redis + Neo4j)")

    finally:
        # Limpiar los datos temporales de esta prueba
        if id_viaje is not None:
            coleccion.delete_one({"_id": id_viaje})
            compensar_viaje_neo4j(neo4j_driver, id_viaje)

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
        neo4j_driver.close()


if __name__ == "__main__":
    main()
