from datetime import datetime, timezone
from uuid import UUID

from app.conexiones import (
    conectar_cassandra,
    conectar_redis,
    conectar_mongodb,
)
from app.repositorio_telemetria import registrar_medicion_cassandra
from app.repositorio_eventos import (
    registrar_evento,
    actualizar_evento,
)

from app.recuperacion_telemetria import procesar_eventos_incompletos

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

    datos = datos.copy()
    datos["vehiculo_patente"] = datos["vehiculo_patente"].strip()

    cluster = None
    cliente_redis = None
    cliente_mongo = None
    coleccion = None
    id_evento = str(datos["id_evento"])

    try:
        # 1. Registrar el evento en MongoDB antes de procesarlo.
        cliente_mongo = conectar_mongodb()
        coleccion = cliente_mongo["logistica"]["eventos_telemetria"]

        evento, creado = registrar_evento(
            coleccion,
            id_evento,
            datos
        )

        # Si ya está completado, no repetir el procesamiento.
        if evento.get("estado_procesamiento") == "COMPLETADO":
            return True, {
                "id_evento": id_evento,
                "estado_procesamiento": "COMPLETADO",
                "motivo": "El evento ya estaba procesado"
            }

        if not actualizar_evento(
            coleccion,
            id_evento,
            estado_procesamiento="PROCESANDO",
            error=None
        ):
            raise RuntimeError(
                "No se pudo actualizar el estado del evento en MongoDB"
            )

        # 2. Guardar en Cassandra solamente si todavía falta.
        cluster, sesion = conectar_cassandra()

        evento = coleccion.find_one({"_id": id_evento})

        if evento is None:
            raise RuntimeError("El evento ya no existe en MongoDB")

        if evento.get("cassandra_guardado") is not True:
            resultado = registrar_medicion_cassandra(sesion, datos)

            if not actualizar_evento(
                coleccion,
                id_evento,
                cassandra_guardado=True,
                error=None
            ):
                raise RuntimeError(
                    "Cassandra guardó la medición, pero no se pudo "
                    "actualizar el progreso en MongoDB"
                )
        else:
            resultado = {
                "id_evento": id_evento,
                "vehiculo_patente": datos["vehiculo_patente"],
                "viaje_id": datos.get("viaje_id"),
                "historial_vehiculo_guardado": True,
                "historial_viaje_guardado": bool(datos.get("viaje_id"))
            }

        # 3. Actualizar Redis solamente si todavía falta.
        evento = coleccion.find_one({"_id": id_evento})

        if evento is None:
            raise RuntimeError("El evento ya no existe en MongoDB")

        if evento.get("redis_procesado") is not True:
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

            cliente_redis = conectar_redis()

            with open(
                "redis/06_update_if_newer.lua",
                encoding="utf-8"
            ) as archivo:
                script = archivo.read()

            sha = cliente_redis.script_load(script)
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

            if not actualizar_evento(
                coleccion,
                id_evento,
                redis_procesado=True,
                estado_actualizado_en_redis=(actualizado == 1),
                error=None
            ):
                raise RuntimeError(
                    "Redis procesó la medición, pero no se pudo "
                    "actualizar el progreso en MongoDB"
                )

            resultado["estado_actualizado_en_redis"] = actualizado == 1
            resultado["motivo_estado_redis"] = (
                "actualizado"
                if actualizado == 1
                else "medición antigua o repetida; se conserva el estado actual"
            )
        else:
            resultado["estado_actualizado_en_redis"] = evento.get(
                "estado_actualizado_en_redis",
                False
            )
            resultado["motivo_estado_redis"] = (
                "El evento ya había sido procesado por Redis"
            )

        # 4. Confirmar los indicadores de ambos motores.
        evento = coleccion.find_one({"_id": id_evento})

        if evento is None:
            raise RuntimeError("El evento ya no existe en MongoDB")

        if (
            evento.get("cassandra_guardado") is not True
            or evento.get("redis_procesado") is not True
        ):
            raise RuntimeError(
                "El evento todavía tiene operaciones pendientes"
            )

        # 5. Marcar como COMPLETADO y verificar el estado persistido.
        if not actualizar_evento(
            coleccion,
            id_evento,
            estado_procesamiento="COMPLETADO",
            error=None
        ):
            raise RuntimeError(
                "No se pudo marcar el evento como COMPLETADO"
            )

        evento_final = coleccion.find_one({"_id": id_evento})

        if (
            evento_final is None
            or evento_final.get("cassandra_guardado") is not True
            or evento_final.get("redis_procesado") is not True
            or evento_final.get("estado_procesamiento") != "COMPLETADO"
        ):
            raise RuntimeError(
                "No se pudo confirmar el estado COMPLETADO en MongoDB"
            )

        resultado["id_evento"] = id_evento
        resultado["estado_procesamiento"] = "COMPLETADO"

        return True, resultado

    except Exception as error:
        if coleccion is not None:
            try:
                evento_actual = coleccion.find_one({"_id": id_evento})

                # No cambiar un evento que ya estaba completado.
                if (
                    evento_actual is not None
                    and evento_actual.get("estado_procesamiento") != "COMPLETADO"
                ):
                    actualizar_evento(
                        coleccion,
                        id_evento,
                        estado_procesamiento="ERROR",
                        error=str(error)
                    )

            except Exception:
                # Conservamos el error original si MongoDB tampoco responde.
                pass

        return False, (
            "La operación no pudo completarse en todos los motores. "
            f"Detalle: {error}"
        )

    finally:
        if cluster is not None:
            try:
                cluster.shutdown()
            except Exception:
                pass

        if cliente_redis is not None:
            try:
                cliente_redis.close()
            except Exception:
                pass

        if cliente_mongo is not None:
            try:
                cliente_mongo.close()
            except Exception:
                pass

def recuperar_telemetria_pendiente(limite=100):
    """
    Ejecuta manualmente la recuperación de eventos incompletos.

    Abre las conexiones necesarias, procesa un lote de eventos
    y cierra las conexiones al finalizar.
    """
    cliente_mongo = None
    cluster = None

    try:
        # 1. Conectar a MongoDB, donde se registra el progreso.
        cliente_mongo = conectar_mongodb()
        coleccion = cliente_mongo["logistica"]["eventos_telemetria"]

        # 2. Abrir una sesión de Cassandra para los reintentos.
        cluster, sesion = conectar_cassandra()

        # 3. Recuperar los eventos incompletos.
        resultado = procesar_eventos_incompletos(
            coleccion,
            sesion,
            limite=limite
        )

        return True, resultado

    except Exception as error:
        return False, (
            "No se pudo completar la recuperación manual. "
            f"Detalle: {error}"
        )

    finally:
        if cluster is not None:
            try:
                cluster.shutdown()
            except Exception:
                pass

        if cliente_mongo is not None:
            try:
                cliente_mongo.close()
            except Exception:
                pass