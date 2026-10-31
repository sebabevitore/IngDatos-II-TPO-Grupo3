import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.conexiones import conectar_neo4j
from app.repositorio_eta_neo4j import obtener_recorrido_viaje, obtener_tramo


def cargar_datos_de_prueba(driver):
    """Crea (si no existen) una ruta de 3 puntos y un viaje asignado a ella."""
    cypher = """
    MERGE (p1:PuntoEntrega {punto_entrega_id: 'P-1'})
      ON CREATE SET p1.nombre = 'Depósito', p1.latitud = -34.60, p1.longitud = -58.40

    MERGE (p2:PuntoEntrega {punto_entrega_id: 'P-2'})
      ON CREATE SET p2.nombre = 'Cliente A', p2.latitud = -34.61, p2.longitud = -58.42

    MERGE (p3:PuntoEntrega {punto_entrega_id: 'P-3'})
      ON CREATE SET p3.nombre = 'Cliente B', p3.latitud = -34.63, p3.longitud = -58.45

    MERGE (r:Ruta {ruta_id: 'RUTA-PRUEBA-1'})
      ON CREATE SET r.estado = 'HABILITADA'

    MERGE (r)-[:INCLUYE {orden: 1}]->(p1)
    MERGE (r)-[:INCLUYE {orden: 2}]->(p2)
    MERGE (r)-[:INCLUYE {orden: 3}]->(p3)

    MERGE (p1)-[c1:CONECTA {tramo_id: 'T-1-2'}]->(p2)
      ON CREATE SET c1.distancia_km = 3.8, c1.tiempo_estimado_min = 8, c1.habilitado = true

    MERGE (p2)-[c2:CONECTA {tramo_id: 'T-2-3'}]->(p3)
      ON CREATE SET c2.distancia_km = 5.1, c2.tiempo_estimado_min = 12, c2.habilitado = true

    MERGE (v:Viaje {viaje_id: 'VIAJE-PRUEBA-ETA'})
      ON CREATE SET v.estado = 'EN_CURSO'
    MERGE (v)-[:ASIGNADO_A]->(r)
    """
    with driver.session() as sesion:
        sesion.run(cypher)
    print("Datos de prueba cargados (o ya existían).")


def main():
    driver = conectar_neo4j()
    try:
        cargar_datos_de_prueba(driver)

        print("\n--- Recorrido del viaje VIAJE-PRUEBA-ETA ---")
        recorrido = obtener_recorrido_viaje(driver, "VIAJE-PRUEBA-ETA")
        for punto in recorrido:
            print(punto)

        print("\n--- Tramo entre P-1 y P-2 ---")
        tramo = obtener_tramo(driver, "P-1", "P-2")
        print(tramo)

    finally:
        driver.close()


if __name__ == "__main__":
    main()