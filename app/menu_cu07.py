import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.conexiones import conectar_neo4j
from app.rutas_alternativas import consultar_impacto_y_alternativa

def preparar_datos_prueba():
    """Genera un sub-grafo idempotente (MERGE) para probar el desvío sin fallas."""
    driver = conectar_neo4j()
    cypher = """
    // Nodos
    MERGE (p1:PuntoEntrega {punto_entrega_id: 'NODO-A'}) ON CREATE SET p1.nombre = 'Centro'
    MERGE (p2:PuntoEntrega {punto_entrega_id: 'NODO-B'}) ON CREATE SET p2.nombre = 'Paso Obligado'
    MERGE (p3:PuntoEntrega {punto_entrega_id: 'NODO-C'}) ON CREATE SET p3.nombre = 'Destino'
    MERGE (p4:PuntoEntrega {punto_entrega_id: 'NODO-D'}) ON CREATE SET p4.nombre = 'Desvío Oculto'

    // Ruta y Viaje afectados
    MERGE (r:Ruta {ruta_id: 'RUTA-SUR-01'})
    MERGE (r)-[:INCLUYE]->(p2)
    MERGE (v:Viaje {viaje_id: 'VIAJE-999'}) ON CREATE SET v.estado = 'EN_CURSO'
    MERGE (v)-[:ASIGNADO_A]->(r)

    // Tramos del camino principal (A -> B -> C)
    MERGE (p1)-[c1:CONECTA {tramo_id: 'TR-AB'}]->(p2) ON CREATE SET c1.distancia_km = 10, c1.tiempo_estimado_min = 15, c1.habilitado = true
    MERGE (p2)-[c2:CONECTA {tramo_id: 'TR-BC'}]->(p3) ON CREATE SET c2.distancia_km = 10, c2.tiempo_estimado_min = 15, c2.habilitado = true

    // Tramos del camino de desvío (A -> D -> C)
    MERGE (p1)-[c3:CONECTA {tramo_id: 'TR-AD'}]->(p4) ON CREATE SET c3.distancia_km = 15, c3.tiempo_estimado_min = 20, c3.habilitado = true
    MERGE (p4)-[c4:CONECTA {tramo_id: 'TR-DC'}]->(p3) ON CREATE SET c4.distancia_km = 12, c4.tiempo_estimado_min = 18, c4.habilitado = true
    """
    with driver.session() as sesion:
        sesion.run(cypher)
    driver.close()
    print("[OK] Red de prueba inicializada en Neo4j.")

def demo_desvio_exitoso():
    print("\n--- 1. ESCENARIO: Camino alternativo exitoso ---")
    print("El vehículo va de NODO-A a NODO-C, pero bloqueamos NODO-B por un piquete.")
    resultado = consultar_impacto_y_alternativa("NODO-A", "NODO-C", "NODO-B")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))

def demo_sin_salida():
    print("\n--- 2. ESCENARIO: Sin ruta alternativa posible ---")
    print("Bloqueamos el NODO-D. Como no hay otra conexión, no se encontrará ruta.")
    resultado = consultar_impacto_y_alternativa("NODO-A", "NODO-C", "NODO-D")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))

def menu():
    preparar_datos_prueba()
    while True:
        print("\n=============================================================")
        print("   TPO - CU-07: Rutas Alternativas y Bloqueos (Neo4j)")
        print("=============================================================")
        print("1. Encontrar camino alternativo por bloqueo")
        print("2. Demostrar falla cuando no hay conexión disponible")
        print("3. Salir")
        opc = input("\nSeleccione (1-3): ").strip()

        if opc == "1":
            demo_desvio_exitoso()
        elif opc == "2":
            demo_sin_salida()
        elif opc == "3":
            print("Saliendo...")
            break
        else:
            print("Opción inválida.")

if __name__ == "__main__":
    menu()