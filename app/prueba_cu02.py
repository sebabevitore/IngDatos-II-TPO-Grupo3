
from app.telemetria import registrar_telemetria

medicion = {
    "id_evento": "550e8400-e29b-41d4-a716-446655440000",
    "vehiculo_patente": "AB123CD",
    "fecha_hora": "2026-10-28T15:30:00-03:00",
    "latitud": -34.6037,
    "longitud": -58.3816,
    "velocidad": 45.5,
    "estado_vehiculo": "EN_MOVIMIENTO",
    "viaje_id": "VIAJE-1001",
}

exito, resultado = registrar_telemetria(medicion)

print("Éxito:", exito)
print("Resultado:", resultado)
