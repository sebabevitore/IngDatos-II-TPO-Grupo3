from uuid import uuid4

from app.viajes import validar_viaje
from app.reservas import (
    reservar_recursos,
    liberar_recurso,
    confirmar_recurso
)
from app.repositorio_viajes import (
    registrar_viaje,
    eliminar_viaje
)
from app.repositorio_rutas_neo4j import (
    vincular_viaje_ruta_neo4j,
    compensar_viaje_neo4j
)


def planificar_viaje(cliente_redis, coleccion_mongo, datos, driver_neo4j=None):
    """
    Orquestador Saga para el Caso de Uso 1 (MongoDB + Redis + Neo4j).
    
    Flujo de ejecución justificado:
      1. [Redis] Reserva atómica temporal de vehículo y chofer (lock en memoria con TTL).
      2. [Neo4j] Validación y vinculación del viaje a su ruta en el grafo vial.
      3. [MongoDB] Registro del viaje y documentos de negocio.
      4. [Redis] Confirmación definitiva de las reservas (quita expiración temporal).
      
    Manejo de compensaciones (Rollback):
      - Si falla Neo4j: Se liberan las reservas en Redis.
      - Si falla MongoDB: Se elimina el viaje de Neo4j y se liberan las reservas en Redis.
      - Si falla la confirmación final de Redis: Se deshace MongoDB, se deshace Neo4j y se liberan los locks.
    """
    valido, mensaje = validar_viaje(datos)

    if not valido:
        return False, mensaje

    # 1. [Redis] Reservar recursos temporalmente
    reservado, resultado = reservar_recursos(
        cliente_redis,
        datos["id_vehiculo"],
        datos["id_conductor"]
    )

    if not reservado:
        return False, resultado

    token = resultado
    clave_vehiculo = f"reserva:vehiculo:{datos['id_vehiculo']}"
    clave_conductor = f"reserva:conductor:{datos['id_conductor']}"

    # Identificador compartido del viaje para todos los motores
    id_viaje = str(uuid4())
    neo4j_vinculado = False
    mongo_registrado = False

    try:
        # 2. [Neo4j] Vincular el viaje al recorrido en la red logística
        if driver_neo4j is not None:
            vincular_viaje_ruta_neo4j(
                driver_neo4j,
                id_viaje=id_viaje,
                id_ruta=datos["id_ruta"],
                id_vehiculo=datos["id_vehiculo"],
                id_conductor=datos["id_conductor"]
            )
            neo4j_vinculado = True

        # 3. [MongoDB] Registrar el viaje en MongoDB
        registrar_viaje(
            coleccion_mongo,
            datos,
            id_operacion=token,
            id_viaje=id_viaje
        )
        mongo_registrado = True

        # 4. [Redis] Confirmar ambas reservas en Redis (permanente)
        confirmado_vehiculo = confirmar_recurso(
            cliente_redis, clave_vehiculo, token
        )

        confirmado_conductor = confirmar_recurso(
            cliente_redis, clave_conductor, token
        )

        if confirmado_vehiculo != 1 or confirmado_conductor != 1:
            raise RuntimeError(
                "No se pudieron confirmar ambas reservas en Redis"
            )

        return True, {
            "id_viaje": id_viaje,
            "estado": "PLANIFICADO",
            "neo4j_vinculado": neo4j_vinculado,
            "id_operacion": token
        }

    except Exception as error:
        # Compensación en MongoDB si se llegó a registrar
        if mongo_registrado:
            try:
                eliminar_viaje(coleccion_mongo, id_viaje)
            except Exception:
                pass

        # Compensación en Neo4j si se llegó a vincular
        if neo4j_vinculado and driver_neo4j is not None:
            try:
                compensar_viaje_neo4j(driver_neo4j, id_viaje)
            except Exception:
                pass

        # Liberar solamente las reservas propias en Redis
        try:
            liberar_recurso(cliente_redis, clave_vehiculo, token)
            liberar_recurso(cliente_redis, clave_conductor, token)
        except Exception:
            pass

        return False, f"Operacion compensada: {error}"
