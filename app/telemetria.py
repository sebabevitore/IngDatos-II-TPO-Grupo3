
from datetime import datetime, timezone
from uuid import UUID

from app.conexiones import conectar_cassandra, conectar_redis
from app.repositorio_telemetria import registrar_medicion_cassandra


def validar_medicion(datos):
    """Valida los datos recibidos para una medición GPS."""

    campos_obligatorios = [
        "id_evento",
        "vehiculo_patente",
        "fecha_hora",
        "latitud",
        "longitud",
        "velocidad",
        "estado_vehiculo",
    ]

    for campo in campos_obligatorios:
        if campo not in datos or datos[campo] is None:
            return False, f"Falta el campo obligatorio: {campo}"

    try:
        UUID(str(datos["id_evento"]))
    except (ValueError, TypeError, AttributeError):
        return False, "id_evento debe ser un UUID válido"

    if not isinstance(datos["vehiculo_patente"], str):
        return False, "La patente debe ser texto"

    if not datos["vehiculo_patente"].strip():
        return False, "La patente no puede estar vacía"

    try:
        fecha = datetime.fromisoformat(
            str(datos["fecha_hora"]).replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return False, "fecha_hora debe tener un formato de fecha válido"

    if fecha.tzinfo is None:
        return False, "fecha_hora debe incluir la zona horaria"

    try:
        latitud = float(datos["latitud"])
        longitud = float(datos["longitud"])
        velocidad = float(datos["velocidad"])
    except (ValueError, TypeError):
        return False, "Latitud, longitud y velocidad deben ser numéricas"

    if not -90 <= latitud <= 90:
        return False, "La latitud debe estar entre -90 y 90"

    if not -180 <= longitud <= 180:
        return False, "La longitud debe estar entre -180 y 180"

    if velocidad < 0:
        return False, "La velocidad no puede ser negativa"

    if not isinstance(datos["estado_vehiculo"], str):
        return False, "El estado del vehículo debe ser texto"

    if not datos["estado_vehiculo"].strip():
        return False, "El estado del vehículo no puede estar vacío"

    viaje_id = datos.get("viaje_id")
    if viaje_id is not None and (
        not isinstance(viaje_id, str) or not viaje_id.strip()
    ):
        return False, "viaje_id debe ser texto no vacío o None"

    return True, "Medición válida"


def registrar_telemetria(datos):
    valido, mensaje = validar_medicion(datos)

    if not valido:
        return False, mensaje

    cluster = None
    cliente_redis = None

    try:
        # 1. Guardar la medición histórica en Cassandra.
        cluster, sesion = conectar_cassandra()
        resultado = registrar_medicion_cassandra(sesion, datos)

        # 2. Preparar los valores para actualizar el estado en Redis.
        fecha = datetime.fromisoformat(
            str(datos["fecha_hora"]).replace("Z", "+00:00")
        )
        fecha_utc = fecha.astimezone(timezone.utc)
        fecha_hora_ms = int(fecha_utc.timestamp() * 1000)

        patente = datos["vehiculo_patente"].strip()
        viaje_id = datos.get("viaje_id") or ""

        latitud = float(datos["latitud"])
        longitud = float(datos["longitud"])
        velocidad = float(datos["velocidad"])
        estado = datos["estado_vehiculo"].strip()

        # 3. Conectar con Redis y cargar el script Lua.
        cliente_redis = conectar_redis()

        with open(
            "redis/06_update_if_newer.lua",
            encoding="utf-8"
        ) as archivo:
            script = archivo.read()

        sha = cliente_redis.script_load(script)

        # 4. Actualizar solamente si la medición es más reciente.
        clave = f"vehiculo:{patente}:estado"

        actualizado = cliente_redis.evalsha(
            sha,
            1,
            clave,
            fecha_hora_ms,
            viaje_id,
            latitud,
            longitud,
            velocidad,
            estado,
        )

        resultado["estado_actualizado_en_redis"] = actualizado == 1
        resultado["motivo_estado_redis"] = (
            "actualizado"
            if actualizado == 1
            else "medición antigua o repetida; se conserva el estado actual"
        )

        return True, resultado

    except Exception as error:
        return False, (
            "La operación no pudo completarse en todos los motores. "
            f"Detalle: {error}"
        )

    finally:
        if cluster is not None:
            cluster.shutdown()

        if cliente_redis is not None:
            cliente_redis.close()
