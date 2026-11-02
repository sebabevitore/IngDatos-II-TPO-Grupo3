"""CU01 persistente: reservas, recorrido y asignaciones, con compensación explícita."""

from datetime import datetime, timezone
from uuid import uuid4
from app.viajes import validar_viaje
from app.reservas import reservar_recursos, liberar_recurso, confirmar_recurso
from app.repositorio_viajes import registrar_viaje
from app.repositorio_rutas_neo4j import vincular_viaje_ruta_neo4j, compensar_viaje_neo4j


def planificar_viaje(
    cliente_redis, coleccion_mongo, datos, driver_neo4j=None, inyector=None
):
    valido, mensaje = validar_viaje(datos)
    if not valido:
        return False, mensaje
    if driver_neo4j is None:
        return False, "CU01 requiere Neo4j para validar el recorrido"
    if coleccion_mongo.database.name != "logistica_flota":
        return False, "Los viajes deben registrarse en logistica_flota.viajes"
    db = coleccion_mongo.database
    viaje = str(uuid4())
    token = None
    locks = []

    def exigir(ok, msg):
        if not ok:
            raise RuntimeError(msg)

    def comprobar_maestros():
        exigir(
            db.vehiculos.find_one({"_id": datos["id_vehiculo"], "estado": "DISPONIBLE"})
            is not None,
            "Vehículo no disponible",
        )
        exigir(
            db.conductores.find_one(
                {"_id": datos["id_conductor"], "estado": "DISPONIBLE"}
            )
            is not None,
            "Conductor no disponible",
        )
        abiertos = {
            "estado": {
                "$nin": ["FINALIZADO", "CANCELADO", "ANULADO", "INTERRUMPIDO_AVERIA"]
            },
            "$or": [
                {"vehiculo_patente": datos["id_vehiculo"]},
                {"id_vehiculo": datos["id_vehiculo"]},
                {"conductor_id": datos["id_conductor"]},
                {"id_conductor": datos["id_conductor"]},
            ],
        }
        exigir(
            db.viajes.count_documents(abiertos) == 0,
            "El vehículo o conductor tiene un viaje abierto",
        )
        for codigo in datos["paquetes"]:
            p = db.paquetes.find_one({"_id": codigo, "estado": "PENDIENTE"})
            exigir(p is not None, f"Paquete no pendiente: {codigo}")
            exigir(
                p["punto_entrega_id"] in puntos,
                "El destino del paquete no pertenece a la ruta",
            )
            exigir(
                db.asignaciones.count_documents(
                    {"paquete_codigo": codigo, "estado": "ACTIVA"}
                )
                == 0,
                "Paquete ya asignado",
            )

    try:
        with driver_neo4j.session() as s:
            puntos = [
                r["id"]
                for r in s.run(
                    "MATCH (r:Ruta {ruta_id:$ruta,estado:'HABILITADA'})-[i:INCLUYE]->(p:PuntoEntrega) RETURN p.punto_entrega_id AS id ORDER BY i.orden",
                    ruta=datos["id_ruta"],
                )
            ]
        exigir(
            len(puntos) >= 2,
            "La ruta no está habilitada o no tiene un recorrido válido",
        )
        comprobar_maestros()
        ok, token = reservar_recursos(
            cliente_redis, datos["id_vehiculo"], datos["id_conductor"]
        )
        if not ok:
            return False, token
        for codigo in sorted(datos["paquetes"]):
            clave = f"reserva:paquete:{codigo}"
            exigir(
                cliente_redis.set(clave, token, nx=True, ex=300),
                "Otro coordinador está asignando un paquete",
            )
            locks.append(clave)
        # Revalidar después de obtener todas las reservas; la lista inicial puede haber cambiado.
        comprobar_maestros()
        db.operaciones.insert_one(
            dict(
                _id=token,
                tipo="PLANIFICACION",
                viaje_id=viaje,
                estado="PROCESANDO",
                fecha_inicio=datetime.now(timezone.utc),
                pasos=[],
            )
        )
        if inyector:
            inyector.verificar("CU01_NEO4J")
        vincular_viaje_ruta_neo4j(
            driver_neo4j,
            viaje,
            datos["id_ruta"],
            datos["id_vehiculo"],
            datos["id_conductor"],
        )
        db.operaciones.update_one({"_id": token}, {"$push": {"pasos": "NEO4J"}})
        if inyector:
            inyector.verificar("CU01_MONGO")
        ahora = datetime.now(timezone.utc)
        payload = dict(
            datos,
            paradas=[
                dict(orden=i + 1, punto_entrega_id=p, estado="PENDIENTE")
                for i, p in enumerate(puntos)
            ],
        )
        registrar_viaje(coleccion_mongo, payload, id_operacion=token, id_viaje=viaje)
        for i, codigo in enumerate(datos["paquetes"]):
            paquete = db.paquetes.find_one({"_id": codigo})
            db.asignaciones.insert_one(
                dict(
                    _id=f"ASIG-{viaje}-{i}",
                    viaje_id=viaje,
                    paquete_codigo=codigo,
                    punto_inicio_id=puntos[0],
                    punto_fin_id=paquete["punto_entrega_id"],
                    estado="ACTIVA",
                    fecha_asignacion=ahora,
                )
            )
            res = db.paquetes.update_one(
                {"_id": codigo, "estado": "PENDIENTE"},
                {"$set": {"estado": "ASIGNADO", "viaje_actual_id": viaje}},
            )
            exigir(
                res.modified_count == 1,
                "El paquete dejó de estar disponible durante la operación",
            )
            if inyector:
                inyector.verificar("CU01_PAQUETES")
        for coll, codigo in (
            (db.vehiculos, datos["id_vehiculo"]),
            (db.conductores, datos["id_conductor"]),
        ):
            exigir(
                coll.update_one(
                    {"_id": codigo, "estado": "DISPONIBLE"},
                    {"$set": {"estado": "RESERVADO", "viaje_actual_id": viaje}},
                ).modified_count
                == 1,
                "El recurso dejó de estar disponible",
            )
        db.operaciones.update_one({"_id": token}, {"$push": {"pasos": "MONGODB"}})
        exigir(
            confirmar_recurso(
                cliente_redis, f'reserva:vehiculo:{datos["id_vehiculo"]}', token
            )
            == 1,
            "No se confirmó el vehículo",
        )
        if inyector:
            inyector.verificar("CU01_REDIS_CONFIRM")
        exigir(
            confirmar_recurso(
                cliente_redis, f'reserva:conductor:{datos["id_conductor"]}', token
            )
            == 1,
            "No se confirmó el conductor",
        )
        db.operaciones.update_one(
            {"_id": token},
            {
                "$set": {
                    "estado": "COMPLETADO",
                    "fecha_fin": datetime.now(timezone.utc),
                },
                "$push": {"pasos": "REDIS_CONFIRMACION"},
            },
        )
        return True, dict(
            id_viaje=viaje,
            id_operacion=token,
            estado="PLANIFICADO",
            neo4j_vinculado=True,
            asignaciones=len(datos["paquetes"]),
        )
    except Exception as error:
        errores = []
        acciones = [
            lambda: db.asignaciones.delete_many({"viaje_id": viaje}),
            lambda: db.viajes.delete_one({"_id": viaje}),
            lambda: db.paquetes.update_many(
                {"viaje_actual_id": viaje},
                {"$set": {"estado": "PENDIENTE"}, "$unset": {"viaje_actual_id": ""}},
            ),
            lambda: db.vehiculos.update_many(
                {"viaje_actual_id": viaje},
                {"$set": {"estado": "DISPONIBLE"}, "$unset": {"viaje_actual_id": ""}},
            ),
            lambda: db.conductores.update_many(
                {"viaje_actual_id": viaje},
                {"$set": {"estado": "DISPONIBLE"}, "$unset": {"viaje_actual_id": ""}},
            ),
            lambda: compensar_viaje_neo4j(driver_neo4j, viaje),
        ]
        for accion in acciones:
            try:
                accion()
            except Exception as exc:
                errores.append(type(exc).__name__)
        if token:
            for clave in (
                f'reserva:vehiculo:{datos["id_vehiculo"]}',
                f'reserva:conductor:{datos["id_conductor"]}',
            ):
                try:
                    liberar_recurso(cliente_redis, clave, token)
                except Exception as exc:
                    errores.append(type(exc).__name__)
            try:
                db.operaciones.update_one(
                    {"_id": token},
                    {
                        "$set": {
                            "estado": (
                                "COMPENSACION_PENDIENTE" if errores else "COMPENSADO"
                            ),
                            "error": str(error),
                            "errores_compensacion": errores,
                        },
                        "$setOnInsert": {
                            "tipo": "PLANIFICACION",
                            "viaje_id": viaje,
                            "fecha_inicio": datetime.now(timezone.utc),
                            "pasos": [],
                        },
                    },
                    upsert=True,
                )
            except Exception as exc:
                errores.append(type(exc).__name__)
        return False, dict(
            error=str(error),
            compensado=not errores,
            errores_compensacion=errores,
            id_viaje=viaje,
        )
    finally:
        for clave in locks:
            if token:
                liberar_recurso(cliente_redis, clave, token)
