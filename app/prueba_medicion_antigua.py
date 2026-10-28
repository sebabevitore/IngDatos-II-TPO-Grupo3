from app.telemetria import registrar_telemetria

medicion_antigua = {
    "id_evento": "660e8400-e29b-41d4-a716-446655440001",
    "vehiculo_patente": "AB123CD",
    "fecha_hora": "2026-10-28T15:20:00-03:00",
    "latitud": -34.6100,
    "longitud": -58.3900,
    "velocidad": 20.0,
    "estado_vehiculo": "DETENIDO",
    "viaje_id": "VIAJE-1001",
}

exito, resultado = registrar_telemetria(medicion_antigua)

print("Éxito:", exito)
print("Resultado:", resultado)
