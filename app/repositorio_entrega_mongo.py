"""
Repositorio MongoDB para el Caso de Uso 6 (Confirmación de entrega).
Responsable de actualizar el estado comercial del paquete, cerrar la asignación
como COMPLETADA, guardar los datos del receptor y auditar el Saga en la colección operaciones.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional


def _obtener_db(cliente_mongo):
    return cliente_mongo["logistica_flota"]


def asegurar_paquete_para_entrega_mongo(
    cliente_mongo,
    paquete_codigo: str,
    viaje_id: str,
    punto_entrega_id: str = "PUNTO-NORTE"
):
    """Inicializa un paquete en estado EN_TRANSITO con su asignación ACTIVA de prueba."""
    db = _obtener_db(cliente_mongo)
    ahora = datetime.now(timezone.utc)

    # 1. Asegurar paquete
    db.paquetes.update_one(
        {"_id": paquete_codigo},
        {"$set": {
            "_id": paquete_codigo,
            "codigo_seguimiento": paquete_codigo,
            "estado": "EN_TRANSITO",
            "punto_entrega_id": punto_entrega_id,
            "fecha_registro": ahora
        }, "$unset": {
            "fecha_entrega": "",
            "receptor": ""
        }},
        upsert=True
    )

    # 2. Asegurar asignación activa
    db.asignaciones.delete_many({"paquete_codigo": paquete_codigo})
    db.asignaciones.insert_one({
        "_id": f"ASIG-{viaje_id}-{paquete_codigo}",
        "viaje_id": viaje_id,
        "paquete_codigo": paquete_codigo,
        "punto_inicio_id": "PUNTO-CENTRO",
        "punto_fin_id": punto_entrega_id,
        "estado": "ACTIVA",
        "fecha_asignacion": ahora
    })


def actualizar_entrega_mongo(
    cliente_mongo,
    datos_entrega: Dict[str, Any],
    saga_id: str
) -> Dict[str, Any]:
    """
    Paso 3 del Saga:
    1. Registra el inicio en la bitácora de operaciones.
    2. Actualiza el paquete a estado 'ENTREGADO' con datos del receptor.
    3. Cierra la asignación pasando su estado a 'COMPLETADA'.
    4. Marca la operación como 'COMPLETADO'.
    """
    db = _obtener_db(cliente_mongo)
    ahora = datetime.now(timezone.utc)

    paquete_codigo = str(datos_entrega["paquete_codigo"]).strip()
    viaje_id = str(datos_entrega["viaje_id"]).strip()

    receptor_info = {
        "nombre": datos_entrega.get("receptor_nombre", "Consignatario"),
        "dni": datos_entrega.get("receptor_dni", "00000000"),
        "vinculo": datos_entrega.get("receptor_vinculo", "TITULAR")
    }

    # 1. Log en operaciones
    db.operaciones.insert_one({
        "_id": saga_id,
        "tipo": "CONFIRMACION_ENTREGA",
        "paquete_codigo": paquete_codigo,
        "viaje_id": viaje_id,
        "estado": "PROCESANDO",
        "fecha_inicio": ahora
    })

    # 2. Actualizar Paquete (Solo si no está entregado)
    res_paq = db.paquetes.update_one(
        {"_id": paquete_codigo, "estado": {"$ne": "ENTREGADO"}},
        {"$set": {
            "estado": "ENTREGADO",
            "fecha_entrega": ahora,
            "receptor": receptor_info
        }}
    )
    if res_paq.matched_count == 0:
        raise RuntimeError(f"El paquete {paquete_codigo} ya se encuentra ENTREGADO o no existe en MongoDB.")

    # 3. Cerrar Asignación (ACTIVA -> COMPLETADA)
    res_asig = db.asignaciones.update_one(
        {"paquete_codigo": paquete_codigo, "viaje_id": viaje_id, "estado": "ACTIVA"},
        {"$set": {
            "estado": "COMPLETADA",
            "fecha_fin": ahora,
            "entregado_a": receptor_info
        }}
    )

    # 4. Consolidar en operaciones
    db.operaciones.update_one(
        {"_id": saga_id},
        {"$set": {
            "estado": "COMPLETADO",
            "fecha_fin": datetime.now(timezone.utc)
        }}
    )

    return {
        "paquete_codigo": paquete_codigo,
        "estado_paquete": "ENTREGADO",
        "asignacion_cerrada": res_asig.modified_count == 1
    }


def compensar_entrega_mongo(
    cliente_mongo,
    paquete_codigo: str,
    viaje_id: str,
    saga_id: str
):
    """
    Acción de compensación (Rollback en MongoDB):
    Restaura el paquete a 'EN_TRANSITO' y la asignación a 'ACTIVA'
    si la transacción debió ser cancelada.
    """
    db = _obtener_db(cliente_mongo)

    # Restaurar paquete
    db.paquetes.update_one(
        {"_id": paquete_codigo},
        {"$set": {"estado": "EN_TRANSITO"}, "$unset": {"fecha_entrega": "", "receptor": ""}}
    )

    # Restaurar asignación
    db.asignaciones.update_one(
        {"paquete_codigo": paquete_codigo, "viaje_id": viaje_id, "estado": "COMPLETADA"},
        {"$set": {"estado": "ACTIVA"}, "$unset": {"fecha_fin": "", "entregado_a": ""}}
    )

    # Registrar en operaciones
    db.operaciones.update_one(
        {"_id": saga_id},
        {"$set": {
            "estado": "ROLLBACK_COMPENSADO",
            "fecha_compensacion": datetime.now(timezone.utc)
        }},
        upsert=True
    )


def consultar_paquete_mongo(cliente_mongo, paquete_codigo: str) -> Optional[Dict[str, Any]]:
    """Consulta los datos y estado del paquete en MongoDB."""
    db = _obtener_db(cliente_mongo)
    return db.paquetes.find_one({"_id": paquete_codigo})
