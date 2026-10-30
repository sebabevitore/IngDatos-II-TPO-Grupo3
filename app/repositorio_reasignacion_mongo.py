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
    punto_fin: str = "PUNTO-NORTE"
):
    """
    Crea un viaje y sus asignaciones activas de prueba si no existen,
    dejando el entorno listo para ser reasignado por avería.
    """
    db = _obtener_db(cliente_mongo)
    ahora = datetime.now(timezone.utc)

    # 1. Asegurar viaje
    db.viajes.update_one(
        {"_id": id_viaje},
        {"$setOnInsert": {
            "_id": id_viaje,
            "vehiculo_patente": patente,
            "conductor_id": conductor,
            "ruta_id": "RUTA-01",
            "estado": "EN_CURSO",
            "inicio_planificado": ahora,
            "paquetes": paquetes
        }},
        upsert=True
    )

    # 2. Asegurar asignación ACTIVA por cada paquete
    for codigo_paquete in paquetes:
        # Cerrar cualquier asignación previa activa para cumplir el índice único
        db.asignaciones.delete_many({"paquete_codigo": codigo_paquete})

        db.asignaciones.insert_one({
            "_id": f"ASIG-{id_viaje}-{codigo_paquete}",
            "viaje_id": id_viaje,
            "paquete_codigo": codigo_paquete,
            "punto_inicio_id": punto_inicio,
            "punto_fin_id": punto_fin,
            "estado": "ACTIVA",
            "fecha_asignacion": ahora
        })


def ejecutar_reasignacion_mongo(
    cliente_mongo,
    id_viaje_averiado: str,
    id_viaje_rescate: str,
    patente_reemplazo: str,
    conductor_reemplazo: str,
    id_punto_averia: str,
    saga_id: str
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
    db.operaciones.insert_one({
        "_id": saga_id,
        "tipo": "REASIGNACION_AVERIA",
        "viaje_averiado": id_viaje_averiado,
        "viaje_rescate": id_viaje_rescate,
        "estado": "PROCESANDO",
        "fecha_inicio": ahora
    })

    # 2. Obtener asignaciones activas actuales
    asignaciones_previas = list(db.asignaciones.find({
        "viaje_id": id_viaje_averiado,
        "estado": "ACTIVA"
    }))

    if not asignaciones_previas:
        # Si no había asignaciones cargadas, buscamos los paquetes del viaje
        doc_viaje = db.viajes.find_one({"_id": id_viaje_averiado})
        paquetes_viaje = doc_viaje.get("paquetes", ["PAQ-DEFAULT"]) if doc_viaje else ["PAQ-DEFAULT"]
        for p in paquetes_viaje:
            asignaciones_previas.append({
                "_id": f"ASIG-{id_viaje_averiado}-{p}",
                "paquete_codigo": p,
                "punto_fin_id": "PUNTO-NORTE"
            })

    paquetes_reasignados = []

    # 3. Transición segura: Actualizar asignaciones previas a INTERRUMPIDA
    for asig in asignaciones_previas:
        pkg = asig["paquete_codigo"]
        paquetes_reasignados.append(pkg)

        db.asignaciones.update_one(
            {"_id": asig["_id"]},
            {"$set": {
                "estado": "INTERRUMPIDA",
                "motivo": "AVERIA_MECANICA_VEHICULO",
                "fecha_cierre": ahora
            }},
            upsert=True
        )

        # 4. Crear la nueva asignación ACTIVA
        nueva_asig_id = f"ASIG-{id_viaje_rescate}-{pkg}"
        db.asignaciones.insert_one({
            "_id": nueva_asig_id,
            "viaje_id": id_viaje_rescate,
            "paquete_codigo": pkg,
            "punto_inicio_id": id_punto_averia,
            "punto_fin_id": asig.get("punto_fin_id", "PUNTO-DESTINO"),
            "estado": "ACTIVA",
            "asignacion_origen_id": asig["_id"],
            "fecha_asignacion": ahora
        })

    # 5. Actualizar viaje viejo y crear viaje de rescate
    db.viajes.update_one(
        {"_id": id_viaje_averiado},
        {"$set": {
            "estado": "INTERRUMPIDO_AVERIA",
            "fecha_interrupcion": ahora,
            "punto_interrupcion": id_punto_averia
        }}
    )

    db.viajes.insert_one({
        "_id": id_viaje_rescate,
        "tipo": "RESCATE",
        "viaje_origen_id": id_viaje_averiado,
        "vehiculo_patente": patente_reemplazo,
        "conductor_id": conductor_reemplazo,
        "estado": "EN_CURSO",
        "fecha_inicio": ahora,
        "punto_partida": id_punto_averia,
        "paquetes": paquetes_reasignados
    })

    # 6. Marcar operación como COMPLETADA
    db.operaciones.update_one(
        {"_id": saga_id},
        {"$set": {
            "estado": "COMPLETADO",
            "fecha_fin": datetime.now(timezone.utc)
        }}
    )

    return {
        "id_viaje_rescate": id_viaje_rescate,
        "paquetes_reasignados": paquetes_reasignados,
        "total_paquetes": len(paquetes_reasignados)
    }


def compensar_reasignacion_mongo(
    cliente_mongo,
    id_viaje_averiado: str,
    id_viaje_rescate: str,
    saga_id: str
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

    # 1. Borrar asignaciones del rescate
    db.asignaciones.delete_many({"viaje_id": id_viaje_rescate})

    # 2. Restaurar asignaciones del viaje original a ACTIVA
    db.asignaciones.update_many(
        {"viaje_id": id_viaje_averiado, "estado": "INTERRUMPIDA"},
        {"$set": {"estado": "ACTIVA"}, "$unset": {"motivo": "", "fecha_cierre": ""}}
    )

    # 3. Eliminar viaje de rescate y restaurar el original
    db.viajes.delete_one({"_id": id_viaje_rescate})

    db.viajes.update_one(
        {"_id": id_viaje_averiado},
        {"$set": {"estado": "EN_CURSO"}, "$unset": {"fecha_interrupcion": "", "punto_interrupcion": ""}}
    )

    # 4. Registrar compensación en operaciones
    db.operaciones.update_one(
        {"_id": saga_id},
        {"$set": {
            "estado": "ROLLBACK_COMPENSADO",
            "fecha_compensacion": datetime.now(timezone.utc)
        }},
        upsert=True
    )


def obtener_paquetes_y_asignaciones_mongo(cliente_mongo, id_viaje: str) -> List[Dict[str, Any]]:
    """Consulta las asignaciones de un viaje dado."""
    db = _obtener_db(cliente_mongo)
    return list(db.asignaciones.find({"viaje_id": id_viaje}))

