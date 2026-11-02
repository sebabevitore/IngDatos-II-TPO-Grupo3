"""
Menú Principal Unificado — Persistencia Políglota (TPO Ingeniería de Datos II)
Permite ejecutar y verificar interactivamente los 8 casos de uso del sistema
y sus respectivos escenarios de falla, concurrencia y consistencia.
"""

import os
import sys

# Permite ejecutar directamente el archivo con el botón de Play del editor
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.conexiones import (
    conectar_mongodb,
    conectar_cassandra,
    conectar_redis,
    conectar_neo4j,
)


def probar_conexiones():
    """Verifica el estado de conexión de los 4 motores NoSQL."""
    print("\n" + "=" * 65)
    print("   DIAGNÓSTICO DE CONECTIVIDAD — 4 MOTORES NOSQL")
    print("=" * 65)
    motores_ok = 0

    # 1. MongoDB
    try:
        cliente = conectar_mongodb()
        cliente.admin.command("ping")
        print("  [OK] MongoDB: Conexión exitosa a logistica_flota")
        cliente.close()
        motores_ok += 1
    except Exception as error:
        print(f"  [ERROR] MongoDB: {error}")

    # 2. Apache Cassandra
    try:
        cluster, sesion = conectar_cassandra()
        fila = sesion.execute("SELECT release_version FROM system.local").one()
        version = fila.release_version if fila else "Desconocida"
        print(f"  [OK] Cassandra: Conexión exitosa (v{version})")
        cluster.shutdown()
        motores_ok += 1
    except Exception as error:
        print(f"  [ERROR] Cassandra: {error}")

    # 3. Redis
    try:
        cliente = conectar_redis()
        cliente.ping()
        print("  [OK] Redis: Conexión exitosa en memoria (PING -> PONG)")
        cliente.close()
        motores_ok += 1
    except Exception as error:
        print(f"  [ERROR] Redis: {error}")

    # 4. Neo4j
    try:
        driver = conectar_neo4j()
        with driver.session() as sesion:
            res = sesion.run("RETURN 1 AS test").single()
            assert res and res["test"] == 1
        print("  [OK] Neo4j: Conexión exitosa al grafo")
        driver.close()
        motores_ok += 1
    except Exception as error:
        print(f"  [ERROR] Neo4j: {error}")

    print("-" * 65)
    print(f"Resultado: {motores_ok}/4 motores operativos.")
    print("=" * 65 + "\n")
    return motores_ok == 4


def ejecutar_cu(caso: int):
    """Enruta la ejecución al menú especializado de cada caso de uso."""
    argumentos_originales = sys.argv[:]
    sys.argv = [sys.argv[0]]  # El número del CU no es una subopción del menú hijo.
    try:
        if caso == 1:
            from app.menu_cu01 import menu_cu01

            menu_cu01()
        elif caso == 2:
            from app.menu_cu02 import menu_cu02

            menu_cu02()
        elif caso == 3:
            from app.menu_cu03 import menu as menu_cu03

            menu_cu03()
        elif caso == 4:
            from app.menu_cu04 import menu as menu_cu04

            menu_cu04()
        elif caso == 5:
            from app.menu_cu05 import menu as menu_cu05

            menu_cu05()
        elif caso == 6:
            from app.menu_cu06 import menu as menu_cu06

            menu_cu06()
        elif caso == 7:
            from app.menu_cu07 import menu as menu_cu07

            menu_cu07()
        elif caso == 8:
            from app.menu_cu08 import menu_cu08

            menu_cu08()
        else:
            print(f"[ERROR] Caso de uso CU-{caso:02d} no reconocido.")
    except Exception as err:
        print(
            f"\n[ERROR EN CU-{caso:02d}] Ocurrió una excepción durante la ejecución: {err}"
        )
    finally:
        sys.argv = argumentos_originales


def menu_principal():
    """Menú interactivo unificado para el trabajo práctico."""
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().lower()
        if arg in ["--check", "-c", "check", "diag", "9"]:
            probar_conexiones()
            return
        elif arg.isdigit() and 1 <= int(arg) <= 8:
            ejecutar_cu(int(arg))
            return

    while True:
        print("\n" + "=" * 75)
        print("   SISTEMA DE LOGÍSTICA Y TRACKING DE FLOTA — PERSISTENCIA POLÍGLOTA")
        print("   TPO Ingeniería de Datos II | MongoDB · Cassandra · Redis · Neo4j")
        print("=" * 75)
        print("  1. CU-01: Planificación de un viaje (MongoDB + Redis + Neo4j)")
        print(
            "  2. CU-02: Ingesta GPS y simulación de 50 vehículos (MongoDB + Cassandra + Redis)"
        )
        print("  3. CU-03: Detección y deduplicación de anomalías (Cassandra + Redis)")
        print(
            "  4. CU-04: Cálculo de ETA y detección de desvíos (Redis + Neo4j + Cassandra)"
        )
        print("  5. CU-05: Reasignación por avería y rescate (MongoDB + Redis + Neo4j)")
        print(
            "  6. CU-06: Confirmación de entrega e idempotencia (MongoDB + Cassandra + Redis)"
        )
        print("  7. CU-07: Rutas alternativas y bloqueos viales (Neo4j + Redis)")
        print(
            "  8. CU-08: Trazabilidad integral de un paquete (MongoDB + Cassandra + Neo4j)"
        )
        print(
            "  -------------------------------------------------------------------------"
        )
        print("  9. Diagnóstico de conectividad con los 4 motores")
        print("  0. Salir")
        print("=" * 75)

        try:
            opcion = input("\nSeleccione una opción (0-9): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nFinalizando ejecución.")
            break

        if opcion == "0" or opcion.lower() in ["salir", "exit"]:
            print("\nFinalizando ejecución. ¡Hasta luego!")
            break
        elif opcion == "9":
            probar_conexiones()
        elif opcion.isdigit() and 1 <= int(opcion) <= 8:
            ejecutar_cu(int(opcion))
        else:
            print("[AVISO] Opción inválida. Ingrese un número del 0 al 9.")


if __name__ == "__main__":
    menu_principal()
