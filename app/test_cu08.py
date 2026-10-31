
from app.trazabilidad import consultar_trazabilidad_completa


def main():
    print("\n=== PRUEBAS INTEGRALES CU-08 ===")

    # Prueba 1: paquete existente con transferencia.
    resultado = consultar_trazabilidad_completa(
        "PAQ-CU08-001"
    )

    assert resultado["exito"] is True
    assert resultado["total_viajes"] == 2
    assert resultado["total_posiciones_gps"] >= 2
    assert resultado["total_alertas"] >= 1

    viajes = {
        viaje["viaje_id"]: viaje
        for viaje in resultado["viajes"]
    }

    original = viajes["VIAJE-CU08-001"]
    rescate = viajes["VIAJE-CU08-002"]

    assert original["vehiculo"] == "AB123CD"
    assert rescate["vehiculo"] == "AC456EF"

    assert original["estado_asignacion"] == "INTERRUMPIDA"
    assert rescate["estado_asignacion"] == "ACTIVA"

    assert len(original["recorrido"]) == 2
    assert len(rescate["recorrido"]) == 2

    assert original["total_posiciones"] >= 1
    assert rescate["total_posiciones"] >= 1
    assert original["total_alertas"] >= 1

    print("[OK] Paquete con transferencia")
    print("[OK] Vehiculos y asignaciones")
    print("[OK] Recorridos de Neo4j")
    print("[OK] GPS y alertas de Cassandra")

    # Prueba 2: paquete inexistente.
    inexistente = consultar_trazabilidad_completa(
        "PAQ-INEXISTENTE-999"
    )

    assert inexistente["exito"] is False
    assert "error" in inexistente

    print("[OK] Paquete inexistente")

    # Prueba 3: codigo vacio.
    try:
        consultar_trazabilidad_completa("   ")
    except ValueError:
        print("[OK] Codigo vacio rechazado")
    else:
        raise AssertionError(
            "El sistema deberia rechazar un codigo vacio"
        )

    print("\n[OK] TODAS LAS PRUEBAS CU-08 PASARON")


if __name__ == "__main__":
    main()
