
from datetime import datetime, timezone

from app.conexiones import conectar_redis
from app.repositorio_eventos import actualizar_evento
from app.repositorio_telemetria import registrar_medicion_cassandra
from app.repositorio_eventos import actualizar_evento


def obtener_eventos_pendientes(coleccion, limite=100):
    """
    Busca eventos que todavía no terminaron de procesarse.

    Devuelve eventos PENDIENTES o con ERROR, ordenados
    desde los más antiguos.
    """
    if not isinstance(limite, int) or limite <= 0:
        raise ValueError("limite debe ser un entero positivo")

    filtro = {
        "estado_procesamiento": {
            "$in": ["PENDIENTE", "ERROR"]
        }
    }

    return list(
        coleccion.find(filtro)
        .sort("creado_en", 1)
        .limit(limite)
    )


def obtener_eventos_incompletos(coleccion, limite=100):
    """
    Busca eventos donde falte procesar al menos un motor.
    También contempla eventos que quedaron en PROCESANDO
    debido a una interrupción inesperada.
    """
    if not isinstance(limite, int) or limite <= 0:
        raise ValueError("limite debe ser un entero positivo")

    filtro = {
        "estado_procesamiento": {
            "$in": ["PENDIENTE", "ERROR", "PROCESANDO"]
        },
        "$or": [
            {"cassandra_guardado": {"$ne": True}},
            {"redis_procesado": {"$ne": True}}
        ]
    }

    return list(
        coleccion.find(filtro)
        .sort("creado_en", 1)
        .limit(limite)
    )

def reintentar_cassandra(coleccion, id_evento, sesion):
    """
    Reintenta guardar en Cassandra un evento pendiente.

    Si Cassandra guarda la medición, actualiza el indicador
    correspondiente en MongoDB.
    """

    evento = coleccion.find_one({"_id": id_evento})

    if evento is None:
        raise ValueError("No existe el evento solicitado")

    if evento.get("cassandra_guardado") is True:
        return {
            "id_evento": id_evento,
            "cassandra_guardado": True,
            "motivo": "El evento ya figura guardado en Cassandra"
        }

    datos = evento["datos"]

    # Intenta guardar la medición en Cassandra.
    resultado = registrar_medicion_cassandra(sesion, datos)

    # Solo marca el evento como guardado si la función anterior
    # terminó sin lanzar una excepción.
    actualizado = actualizar_evento(
        coleccion,
        id_evento,
        cassandra_guardado=True,
        error=None
    )

    if not actualizado:
        raise RuntimeError(
            "Cassandra guardó la medición, pero no se pudo "
            "actualizar el evento en MongoDB"
        )

    return resultado



def reintentar_redis(coleccion, id_evento):
    """
    Reintenta actualizar el estado actual del vehículo en Redis.

    Si la medición es antigua o repetida, conserva el estado actual,
    pero registra que el procesamiento de Redis se completó.
    """
    evento = coleccion.find_one({"_id": id_evento})

    if evento is None:
        raise ValueError("No existe el evento solicitado")

    if evento.get("redis_procesado") is True:
        return {
            "id_evento": id_evento,
            "redis_procesado": True,
            "motivo": "El evento ya fue procesado por Redis"
        }

    datos = evento["datos"]
    cliente_redis = None

    try:
        # 1. Interpretar la fecha y comprobar la zona horaria.
        fecha = datetime.fromisoformat(
            str(datos["fecha_hora"]).replace("Z", "+00:00")
        )

        if fecha.tzinfo is None:
            raise ValueError(
                "fecha_hora debe incluir zona horaria"
            )

        # 2. Convertir la fecha a UTC y luego a milisegundos.
        fecha_utc = fecha.astimezone(timezone.utc)
        fecha_hora_ms = int(fecha_utc.timestamp() * 1000)

        # 3. Preparar los datos de la medición.
        patente = datos["vehiculo_patente"].strip()
        viaje_id = datos.get("viaje_id") or ""
        latitud = float(datos["latitud"])
        longitud = float(datos["longitud"])
        velocidad = float(datos["velocidad"])
        estado = datos["estado_vehiculo"].strip()

        # 4. Conectar con Redis.
        cliente_redis = conectar_redis()

        # 5. Cargar el script que actualiza solo si la medición
        # es más reciente que el estado actual.
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

        # 6. Registrar en MongoDB que Redis procesó el evento.
        actualizado_en_mongo = actualizar_evento(
            coleccion,
            id_evento,
            redis_procesado=True,
            estado_actualizado_en_redis=(actualizado == 1),
            error=None
        )

        if not actualizado_en_mongo:
            raise RuntimeError(
                "Redis procesó la medición, pero no se pudo "
                "actualizar el evento en MongoDB"
            )

        return {
            "id_evento": id_evento,
            "redis_procesado": True,
            "estado_actualizado_en_redis": actualizado == 1,
            "motivo": (
                "Estado actualizado"
                if actualizado == 1
                else "Medición antigua o repetida; se conserva el estado actual"
            )
        }

    finally:
        if cliente_redis is not None:
            cliente_redis.close()



def recuperar_evento(coleccion, id_evento, sesion_cassandra):
    """
    Recupera un evento incompleto sin repetir las operaciones
    que ya figuran como procesadas.
    """
    evento = coleccion.find_one({"_id": id_evento})

    if evento is None:
        raise ValueError("No existe el evento solicitado")

    if evento.get("estado_procesamiento") == "COMPLETADO":
        return {
            "id_evento": id_evento,
            "estado_procesamiento": "COMPLETADO",
            "motivo": "El evento ya estaba completado"
        }

    try:
        # 1. Marcar el evento como en proceso y verificar el cambio.
        actualizado = actualizar_evento(
            coleccion,
            id_evento,
            estado_procesamiento="PROCESANDO",
            error=None
        )

        if not actualizado:
            raise RuntimeError(
                "No se pudo marcar el evento como PROCESANDO en MongoDB"
            )

        # 2. Recuperar Cassandra si todavía falta guardar la medición.
        evento = coleccion.find_one({"_id": id_evento})

        if evento is None:
            raise RuntimeError(
                "No se encontró el evento en MongoDB durante la recuperación"
            )

        if evento.get("cassandra_guardado") is not True:
            reintentar_cassandra(
                coleccion,
                id_evento,
                sesion_cassandra
            )

        # 3. Recuperar Redis si todavía falta procesar el evento.
        evento = coleccion.find_one({"_id": id_evento})

        if evento is None:
            raise RuntimeError(
                "No se encontró el evento en MongoDB durante la recuperación"
            )

        if evento.get("redis_procesado") is not True:
            reintentar_redis(coleccion, id_evento)

        # 4. Volver a consultar MongoDB para verificar ambos resultados.
        evento = coleccion.find_one({"_id": id_evento})

        if evento is None:
            raise RuntimeError(
                "No se encontró el evento al verificar el resultado final"
            )

        cassandra_ok = evento.get("cassandra_guardado") is True
        redis_ok = evento.get("redis_procesado") is True

        if cassandra_ok and redis_ok:
            estado_final = "COMPLETADO"
            error_final = None
        else:
            estado_final = "ERROR"
            error_final = (
                "El evento todavía tiene operaciones pendientes"
            )

        # 5. Guardar el estado final y comprobar que se persistió.
        actualizado = actualizar_evento(
            coleccion,
            id_evento,
            estado_procesamiento=estado_final,
            error=error_final
        )

        if not actualizado:
            raise RuntimeError(
                "No se pudo guardar el estado final en MongoDB"
            )

        return {
            "id_evento": id_evento,
            "estado_procesamiento": estado_final,
            "cassandra_guardado": cassandra_ok,
            "redis_procesado": redis_ok,
            "error": error_final
        }

    except Exception as error:
        # Intentar registrar el fallo sin ocultar el error original.
        try:
            actualizado = actualizar_evento(
                coleccion,
                id_evento,
                estado_procesamiento="ERROR",
                error=str(error)
            )

            if not actualizado:
                return {
                    "id_evento": id_evento,
                    "estado_procesamiento": "ERROR",
                    "error": str(error),
                    "detalle": (
                        "MongoDB no encontró el evento para guardar el error"
                    )
                }

        except Exception:
            return {
                "id_evento": id_evento,
                "estado_procesamiento": "ERROR",
                "error": str(error),
                "detalle": (
                    "No se pudo registrar el error en MongoDB. "
                    "El estado persistido podría no haberse actualizado."
                )
            }

        return {
            "id_evento": id_evento,
            "estado_procesamiento": "ERROR",
            "error": str(error)
        }


def procesar_eventos_incompletos(
    coleccion,
    sesion_cassandra,
    limite=100
):
    """
    Busca y recupera un lote de eventos incompletos.

    Recibe una sesión Cassandra ya abierta.
    No abre ni cierra las conexiones.
    """
    eventos = obtener_eventos_incompletos(
        coleccion,
        limite=limite
    )

    resultados = []

    for evento in eventos:
        id_evento = evento["_id"]

        resultado = recuperar_evento(
            coleccion,
            id_evento,
            sesion_cassandra
        )

        resultados.append(resultado)

    return {
        "eventos_encontrados": len(eventos),
        "eventos_completados": sum(
            1 for resultado in resultados
            if resultado.get("estado_procesamiento") == "COMPLETADO"
        ),
        "eventos_con_error": sum(
            1 for resultado in resultados
            if resultado.get("estado_procesamiento") == "ERROR"
        ),
        "resultados": resultados
    }
