"""Navegación uniforme, incluyendo ejecución individual y suite de demostraciones."""

import sys


def ejecutar_menu(titulo, opciones, salir, argv=None):
    argumentos = sys.argv[1:] if argv is None else argv
    if argumentos:
        arg = argumentos[0].lower()
        if arg in ("--all", "-a", "all"):
            # Cada función verifica sus invariantes y falla si una demostración no cumple.
            resultados = [funcion() for _, funcion in opciones]
            print(f"[OK] {len(resultados)} escenarios verificados: {titulo}")
            return resultados
        numero = arg.replace("--demo", "")
        if numero.isdigit() and 1 <= int(numero) <= len(opciones):
            return opciones[int(numero) - 1][1]()
        raise ValueError(f"Argumento no reconocido: {arg}")
    while True:
        print(f"\n=== {titulo} ===")
        for i, (nombre, _) in enumerate(opciones, 1):
            print(f"{i}. {nombre}")
        print(f"{salir}. Volver al menú principal")
        try:
            opcion = input("Seleccione una opción: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if opcion in (str(salir), "0", "salir", "exit"):
            return
        if not opcion.isdigit() or not 1 <= int(opcion) <= len(opciones):
            print("Opción inválida.")
            continue
        try:
            opciones[int(opcion) - 1][1]()
        except Exception as error:
            print(f"[ERROR] Demostración no verificada: {error}")
