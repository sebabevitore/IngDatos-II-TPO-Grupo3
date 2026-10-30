"""
Repositorio Cassandra para el Caso de Uso 6 (Confirmación de entrega).
Responsable del registro legal e inmutable de prueba de entrega (Proof of Delivery),
resistente a modificaciones cotidianas y diseñado para trazabilidad histórica.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import Dict, Any, List


def registrar_entrega_cassandra(sesion, datos_entrega: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inserta el evento inmutable de confirmación de entrega en Cassandra.
    
    Clave primaria: ((viaje_id, dia), fecha_hora, paquete_codigo)
    """
    viaje_id = str(datos_entrega["viaje_id"]).strip()
    paquete_codigo = str(datos_entrega["paquete_codigo"]).strip()
    patente = str(datos_entrega["vehiculo_patente"]).strip()

    fecha = datetime.fromisoformat(
        str(datos_entrega["fecha_hora"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    dia = fecha.date()
    fecha_cql = fecha.replace(tzinfo=None)

    id_evento = uuid4()
    lat = float(datos_entrega.get("latitud", 0.0))
    lon = float(datos_entrega.get("longitud", 0.0))

    receptor_nombre = str(datos_entrega.get("receptor_nombre", "Consignatario"))
    receptor_dni = str(datos_entrega.get("receptor_dni", "00000000"))
    receptor_vinculo = str(datos_entrega.get("receptor_vinculo", "TITULAR"))

    cql = """
    INSERT INTO logistica_flota.confirmaciones_entrega_por_viaje_dia
    (viaje_id, dia, fecha_hora, paquete_codigo, vehiculo_patente,
     receptor_nombre, receptor_dni, receptor_vinculo, latitud, longitud, id_evento)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    sesion.execute(
        cql,
        (
            viaje_id, dia, fecha_cql, paquete_codigo, patente,
            receptor_nombre, receptor_dni, receptor_vinculo, lat, lon, id_evento
        )
    )

    return {
        "viaje_id": viaje_id,
        "dia": str(dia),
        "fecha_cql": fecha_cql,
        "paquete_codigo": paquete_codigo,
        "id_evento": str(id_evento),
        "guardado_en_cassandra": True
    }


def compensar_entrega_cassandra(
    sesion,
    viaje_id: str,
    dia,
    fecha_cql,
    paquete_codigo: str
):
    """
    Acción de compensación (Rollback): Si falla MongoDB en el paso siguiente,
    se elimina la fila insertada en Cassandra respetando la clave primaria completa.
    """
    cql = """
    DELETE FROM logistica_flota.confirmaciones_entrega_por_viaje_dia
    WHERE viaje_id = %s AND dia = %s AND fecha_hora = %s AND paquete_codigo = %s
    """
    sesion.execute(
        cql,
        (viaje_id, dia, fecha_cql, paquete_codigo)
    )


def consultar_entregas_viaje_cassandra(
    sesion,
    viaje_id: str,
    dia
) -> List[Dict[str, Any]]:
    """Consulta todas las confirmaciones de entrega de un viaje y día."""
    cql = """
    SELECT viaje_id, dia, fecha_hora, paquete_codigo, vehiculo_patente,
           receptor_nombre, receptor_dni, receptor_vinculo, latitud, longitud, id_evento
    FROM logistica_flota.confirmaciones_entrega_por_viaje_dia
    WHERE viaje_id = %s AND dia = %s
    """
    filas = sesion.execute(cql, (viaje_id, dia))
    resultados = []
    for f in filas:
        resultados.append({
            "viaje_id": f.viaje_id,
            "paquete_codigo": f.paquete_codigo,
            "fecha_hora": f.fecha_hora.isoformat() if f.fecha_hora else "",
            "vehiculo_patente": f.vehiculo_patente,
            "receptor_nombre": f.receptor_nombre,
            "receptor_dni": f.receptor_dni,
            "id_evento": str(f.id_evento)
        })
    return resultados

