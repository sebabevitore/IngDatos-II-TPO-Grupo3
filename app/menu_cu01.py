"""
Menú interactivo y de prueba para el Caso de Uso 1: Planificación de un viaje (MongoDB + Redis + Neo4j).
Permite ejecutar y verificar todos los escenarios exigidos por la consigna (Sección 4, 5 y 8).
"""

import os
import sys

# Permite ejecutar directamente el archivo con el botón de Play del editor
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.prueba_cu01_real import main as demo_camino_feliz
from app.prueba_concurrencia import main as demo_concurrencia
from app.prueba_falla_real import main as demo_falla_y_rollback


def menu_cu01():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--all", "-a", "all"]:
            print("\n--- Ejecutando todos los escenarios de CU-01 ---")
            demo_camino_feliz()
            demo_concurrencia()
            demo_falla_y_rollback()
            return
        elif arg in ["1", "--demo1"]:
            demo_camino_feliz()
            return
        elif arg in ["2", "--demo2"]:
            demo_concurrencia()
            return
        elif arg in ["3", "--demo3"]:
            demo_falla_y_rollback()
            return

    while True:
        print("\n=============================================================")
        print("   TPO - CU-01: Planificación de un viaje (MongoDB + Redis + Neo4j)")
        print("=============================================================")
        print("1. Camino feliz: Planificación real con reserva en Redis y grafo en Neo4j")
        print("2. Concurrencia: Doble reserva simultánea de camión (SET NX atómico)")
        print("3. Demostración de Falla: Error en MongoDB y Rollback Saga")
        print("4. Volver al menú principal")
        opc = input("\nSeleccione una opción (1-4): ").strip()

        if opc == "1":
            try:
                demo_camino_feliz()
            except Exception as e:
                print(f"[ERROR] {e}")
        elif opc == "2":
            try:
                demo_concurrencia()
            except Exception as e:
                print(f"[ERROR] {e}")
        elif opc == "3":
            try:
                demo_falla_y_rollback()
            except Exception as e:
                print(f"[ERROR] {e}")
        elif opc in ["4", "0", "salir", "exit"]:
            break
        else:
            print("Opción inválida.")


if __name__ == "__main__":
    menu_cu01()

