import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.telemetria import registrar_telemetria
from app.eta import calcular_eta_y_desvio


def main():
    print("Registrando una medición de telemetría cerca de P-1, yendo hacia P-2...")
    ok, resultado = registrar_telemetria({
        "id_evento": str(uuid4()),
        "vehiculo_patente": "AA111AA",
        "fecha_hora": datetime.now(timezone.utc).isoformat(),
        "latitud": -34.605,
        "longitud": -58.405,
        "velocidad": 40,
        "estado_vehiculo": "EN_RUTA",
        "viaje_id": "VIAJE-PRUEBA-ETA",
    })
    print("Registro de telemetría:", ok, resultado)

    print("\n--- Calculando ETA y desvío para VIAJE-PRUEBA-ETA ---")
    resultado_eta = calcular_eta_y_desvio("VIAJE-PRUEBA-ETA")
    print(resultado_eta)


if __name__ == "__main__":
    main()