from app.telemetria import registrar_telemetria
from datetime import datetime, timezone
from uuid import uuid4

datos = {
    "id_evento": str(uuid4()),
    "vehiculo_patente": "TEST123",
    "fecha_hora": datetime.now(timezone.utc).isoformat(),
    "latitud": -34.6037,
    "longitud": -58.3816,
    "velocidad": 35.0,
    "estado_vehiculo": "EN_MOVIMIENTO",
    "viaje_id": "VIAJE-TEST-001"
}

resultado = registrar_telemetria(datos)
print(resultado)