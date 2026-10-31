
from app.trazabilidad import consultar_trazabilidad_completa


def mostrar_trazabilidad(resultado):
    """Muestra en consola la trazabilidad de un paquete."""

    if not resultado["exito"]:
        print("\n[ERROR]", resultado["error"])
        return

    print("\n" + "=" * 55)
    print("CU-08: TRAZABILIDAD COMPLETA DEL PAQUETE")
    print("=" * 55)

    print("Codigo:", resultado["codigo_seguimiento"])
    print("Estado:", resultado["estado_paquete"])
    print("Total de viajes:", resultado["total_viajes"])
    print("Total GPS:", resultado["total_posiciones_gps"])
    print("Total alertas:", resultado["total_alertas"])

    for numero, viaje in enumerate(resultado["viajes"], start=1):
        print("\n" + "-" * 55)
        print(f"VIAJE {numero}: {viaje['viaje_id']}")
        print("-" * 55)

        print("Vehiculo:", viaje["vehiculo"])
        print("Conductor:", viaje["conductor"])
        print("Ruta:", viaje["ruta"])
        print("Estado del viaje:", viaje["estado_viaje"])
        print("Estado de asignacion:", viaje["estado_asignacion"])

        periodo = viaje["periodo_asignacion"]
        print("Inicio de asignacion:", periodo["inicio"])
        print("Fin de asignacion:", periodo["fin"] or "ACTIVA")

        print("\nRecorrido planificado:")
        if viaje["recorrido"]:
            for punto in viaje["recorrido"]:
                print(
                    f"  {punto['orden']}. "
                    f"{punto['nombre']} "
                    f"({punto['latitud']}, {punto['longitud']})"
                )
        else:
            print("  Sin recorrido registrado")

        print("\nPosiciones GPS:")
        if viaje["posiciones_gps"]:
            for gps in viaje["posiciones_gps"]:
                print(
                    f"  {gps['fecha_hora']} | "
                    f"Lat: {gps['latitud']} | "
                    f"Lon: {gps['longitud']} | "
                    f"Velocidad: {gps['velocidad']} km/h"
                )
        else:
            print("  Sin posiciones en el periodo")

        print("\nAlertas:")
        if viaje["alertas"]:
            for alerta in viaje["alertas"]:
                print(
                    f"  {alerta['fecha_hora']} | "
                    f"{alerta['tipo']} | "
                    f"{alerta['descripcion']}"
                )
        else:
            print("  Sin alertas en el periodo")

    print("\n" + "=" * 55)
    print("[OK] CONSULTA FINALIZADA")
    print("=" * 55)


def menu_cu08():
    """Permite consultar la trazabilidad desde la consola."""

    while True:
        print("\n=== MENU CU-08 ===")
        print("1. Consultar trazabilidad de un paquete")
        print("0. Volver / Salir")

        opcion = input("\nSeleccione una opcion: ").strip()

        if opcion == "0":
            return

        if opcion == "1":
            codigo = input(
                "Ingrese el codigo de seguimiento: "
            ).strip()

            if not codigo:
                print("[ERROR] El codigo no puede estar vacio")
                continue

            try:
                resultado = consultar_trazabilidad_completa(
                    codigo
                )

                mostrar_trazabilidad(resultado)

            except Exception as error:
                print("[ERROR] No se pudo consultar:", error)

        else:
            print("[ERROR] Opcion no valida")


if __name__ == "__main__":
    menu_cu08()
