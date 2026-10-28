
from app.conexiones import conectar_redis


def consultar_estado_actual(vehiculo_patente):
    """
    Consulta en Redis el último estado conocido de un vehículo.
    """

    if not isinstance(vehiculo_patente, str) or not vehiculo_patente.strip():
        return False, "La patente es obligatoria"

    cliente_redis = None

    try:
        cliente_redis = conectar_redis()

        patente = vehiculo_patente.strip()
        clave = f"vehiculo:{patente}:estado"

        estado = cliente_redis.hgetall(clave)

        if not estado:
            return False, f"No hay estado registrado para el vehículo {patente}"

        return True, {
            "vehiculo_patente": patente,
            "fecha_hora_ms": int(estado["fecha_hora_ms"]),
            "viaje_id": estado.get("viaje_id") or None,
            "latitud": float(estado["latitud"]),
            "longitud": float(estado["longitud"]),
            "velocidad": float(estado["velocidad"]),
            "estado_vehiculo": estado["estado"],
        }

    except Exception as error:
        return False, f"Error al consultar el estado actual: {error}"

    finally:
        if cliente_redis is not None:
            cliente_redis.close()
