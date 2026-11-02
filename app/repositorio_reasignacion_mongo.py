"""
Repositorio MongoDB para el Caso de Uso 5 (Reasignación por avería).
Responsable del cierre de tramos/viajes, reasignación de paquetes
(garantizando que ningún paquete quede sin asignación o con 2 activas),
y registro de auditoría en la colección de operaciones.
"""

from datetime import datetime, timezone
from uuid import uuid4
from typing import Dict, Any, List, Optional


def _obtener_db(cliente_mongo):
    """Devuelve la base de datos oficial del TPO."""
    return cliente_mongo["logistica_flota"]


def asegurar_viaje_prueba_mongo(
    cliente_mongo,
    id_viaje: str,
    patente: str,
    conductor: str,
    paquetes: List[str],
    punto_inicio: str = "PUNTO-CENTRO",
    punto_fin: str = "PUNTO-NORTE",
):
    """
    Crea un viaje y sus asignaciones activas de prueba si no existen,
    dejando el entorno listo para ser reasignado por avería.
    """
    db = _obtener_db(cliente_mongo)
    ahora = datetime.now(timezone.utc)

    if db.viajes.find_one({"_id": id_viaje}) is not None:
        return  # Una fixture procesada no se reinicia ni pierde sus asignaciones históricas.
    if any(
        db.asignaciones.find_one({"paquete_codigo": p, "estado": "ACTIVA"})
        for p in paquetes
    ):
        raise ValueError("Un paquete de la fixture ya tiene asignación activa")
    db.viajes.insert_one(
        dict(
            _id=id_viaje,
            vehiculo_patente=patente,
            conductor_id=conductor,
            ruta_id="RUTA-01",
            estado="EN_CURSO",
            inicio_planificado=ahora,
            paquetes=paquetes,
        )
    )
    for p in paquetes:
        if db.paquetes.find_one({"_id": p}) is None:
            db.paquetes.insert_one(
                dict(
                    _id=p,
                    codigo_seguimiento=p,
                    estado="EN_TRANSITO",
                    punto_entrega_id=punto_fin,
                    fecha_registro=ahora,
                )
            )
        db.asignaciones.insert_one(
            dict(
                _id=f"ASIG-{id_viaje}-{p}",
                viaje_id=id_viaje,
                paquete_codigo=p,
                punto_inicio_id=punto_inicio,
                punto_fin_id=punto_fin,
                estado="ACTIVA",
                fecha_asignacion=ahora,
            )
        )


def ejecutar_reasignacion_mongo(
    cliente_mongo,
    id_viaje_averiado: str,
    id_viaje_rescate: str,
    patente_reemplazo: str,
    conductor_reemplazo: str,
    id_punto_averia: str,
    saga_id: str,
    ruta_rescate_id=None,
    puntos_recorrido=None,
) -> Dict[str, Any]:
    """
    Paso 3 del Saga:
    1. Busca las asignaciones activas del viaje averiado.
    2. Cierra las asignaciones viejas pasándolas a estado 'INTERRUMPIDA'.
    3. Crea las nuevas asignaciones en estado 'ACTIVA' vinculadas al viaje de rescate.
       (El orden estricto de update y luego insert respeta el índice único parcial).
    4. Marca el viaje anterior como 'INTERRUMPIDO_AVERIA' y crea el nuevo viaje de 'RESCATE'.
    5. Registra el avance exitoso en la colección de 'operaciones'.
    """
    db = _obtener_db(cliente_mongo)
    ahora = datetime.now(timezone.utc)

    # 1. Registrar inicio en la bitácora de operaciones
    db.operaciones.insert_one(
        {
            "_id": saga_id,
            "tipo": "REASIGNACION_AVERIA",
            "viaje_averiado": id_viaje_averiado,
            "viaje_rescate": id_viaje_rescate,
            "estado": "PROCESANDO",
            "fecha_inicio": ahora,
        }
    )

    # 2. Obtener asignaciones activas actuales
    asignaciones_previas = list(
        db.asignaciones.find({"viaje_id": id_viaje_averiado, "estado": "ACTIVA"})
    )

    if not asignaciones_previas:
        raise ValueError(
            "El viaje no tiene asignaciones activas; no se inventan paquetes de rescate"
        )
    if any(
        db.paquetes.find_one({"_id": a["paquete_codigo"]}) is None
        for a in asignaciones_previas
    ):
        raise ValueError("Hay asignaciones con paquetes inexistentes")

    paquetes_reasignados = []

    # 3. Transición segura: Actualizar asignaciones previas a INTERRUMPIDA
    for asig in asignaciones_previas:
        pkg = asig["paquete_codigo"]
        paquetes_reasignados.append(pkg)

        db.asignaciones.update_one(
            {"_id": asig["_id"]},
            {
                "$set": {
                    "estado": "INTERRUMPIDA",
                    "motivo": "AVERIA_MECANICA_VEHICULO",
                    "saga_reasignacion": saga_id,
                    "fecha_cierre": ahora,
                }
            },
            upsert=True,
        )

        # 4. Crear la nueva asignación ACTIVA
        nueva_asig_id = f"ASIG-{id_viaje_rescate}-{pkg}"
        db.asignaciones.insert_one(
            {
                "_id": nueva_asig_id,
                "viaje_id": id_viaje_rescate,
                "paquete_codigo": pkg,
                "punto_inicio_id": id_punto_averia,
                "punto_fin_id": asig.get("punto_fin_id", "PUNTO-DESTINO"),
                "estado": "ACTIVA",
                "asignacion_origen_id": asig["_id"],
                "fecha_asignacion": ahora,
            }
        )

    # 5. Actualizar viaje viejo y crear viaje de rescate
    db.viajes.update_one(
        {"_id": id_viaje_averiado},
        {
            "$set": {
                "estado": "INTERRUMPIDO_AVERIA",
                "fecha_interrupcion": ahora,
                "punto_interrupcion": id_punto_averia,
            }
        },
    )

    db.viajes.insert_one(
        {
            "_id": id_viaje_rescate,
            "tipo": "RESCATE",
            "ruta_id": ruta_rescate_id or f"RESCATE-{id_viaje_rescate}",
            "id_ruta": ruta_rescate_id or f"RESCATE-{id_viaje_rescate}",
            "id_vehiculo": patente_reemplazo,
            "id_conductor": conductor_reemplazo,
            "paradas": [
                dict(orden=i + 1, punto_entrega_id=p, estado="PENDIENTE")
                for i, p in enumerate(puntos_recorrido or [])
            ],
            "viaje_origen_id": id_viaje_averiado,
            "vehiculo_patente": patente_reemplazo,
            "conductor_id": conductor_reemplazo,
            "estado": "EN_CURSO",
            "fecha_inicio": ahora,
            "punto_partida": id_punto_averia,
            "paquetes": paquetes_reasignados,
        }
    )

    original = db.viajes.find_one({"_id": id_viaje_averiado})
    vehiculo_original = original.get("vehiculo_patente", original.get("id_vehiculo"))
    db.vehiculos.update_one(
        {"_id": vehiculo_original},
        {"$set": {"estado": "AVERIADO", "ultima_operacion": saga_id}},
    )
    db.vehiculos.update_one(
        {"_id": patente_reemplazo}, {"$set": {"estado": "EN_VIAJE"}}
    )
    db.conductores.update_one(
        {"_id": conductor_reemplazo}, {"$set": {"estado": "ASIGNADO"}}
    )

    # 6. Marcar operación como COMPLETADA
    db.operaciones.update_one(
        {"_id": saga_id},
        {"$set": {"estado": "COMPLETADO", "fecha_fin": datetime.now(timezone.utc)}},
    )

    return {
        "id_viaje_rescate": id_viaje_rescate,
        "paquetes_reasignados": paquetes_reasignados,
        "total_paquetes": len(paquetes_reasignados),
    }


def compensar_reasignacion_mongo(
    cliente_mongo, id_viaje_averiado: str, id_viaje_rescate: str, saga_id: str
):
    """
    Acción de compensación (Rollback en MongoDB):
    1. Elimina las nuevas asignaciones creadas para el viaje de rescate.
    2. Restaura las asignaciones anteriores a estado 'ACTIVA'.
    3. Elimina el documento del viaje de rescate.
    4. Restaura el viaje original a estado 'EN_CURSO'.
    5. Registra el estado 'ROLLBACK_COMPENSADO' en la bitácora de operaciones.
    """
    db = _obtener_db(cliente_mongo)

    rescate = db.viajes.find_one({"_id": id_viaje_rescate})
    # 1. Borrar asignaciones del rescate
    db.asignaciones.delete_many({"viaje_id": id_viaje_rescate})

    # 2. Restaurar asignaciones del viaje original a ACTIVA
    db.asignaciones.update_many(
        {
            "viaje_id": id_viaje_averiado,
            "estado": "INTERRUMPIDA",
            "saga_reasignacion": saga_id,
        },
        {
            "$set": {"estado": "ACTIVA"},
            "$unset": {"motivo": "", "fecha_cierre": "", "saga_reasignacion": ""},
        },
    )

    if rescate:
        db.vehiculos.update_one(
            {"_id": rescate["vehiculo_patente"]}, {"$set": {"estado": "DISPONIBLE"}}
        )
        db.conductores.update_one(
            {"_id": rescate["conductor_id"]}, {"$set": {"estado": "DISPONIBLE"}}
        )
    db.vehiculos.update_many(
        {"ultima_operacion": saga_id},
        {"$set": {"estado": "EN_VIAJE"}, "$unset": {"ultima_operacion": ""}},
    )
    # 3. Eliminar viaje de rescate y restaurar el original
    db.viajes.delete_one({"_id": id_viaje_rescate})

    db.viajes.update_one(
        {"_id": id_viaje_averiado},
        {
            "$set": {"estado": "EN_CURSO"},
            "$unset": {"fecha_interrupcion": "", "punto_interrupcion": ""},
        },
    )

    # 4. Registrar compensación en operaciones
    db.operaciones.update_one(
        {"_id": saga_id},
        {
            "$set": {
                "estado": "ROLLBACK_COMPENSADO",
                "fecha_compensacion": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def obtener_paquetes_y_asignaciones_mongo(
    cliente_mongo, id_viaje: str
) -> List[Dict[str, Any]]:
    """Consulta las asignaciones de un viaje dado."""
    db = _obtener_db(cliente_mongo)
    return list(db.asignaciones.find({"viaje_id": id_viaje}))
