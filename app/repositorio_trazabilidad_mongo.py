def consultar_trazabilidad_mongo(cliente_mongo, codigo_seguimiento):
    """
    Consulta en MongoDB un paquete, todas sus asignaciones
    historicas y los viajes asociados.
    """

    db = cliente_mongo["logistica_flota"]

    paquete = db.paquetes.find_one(
        {
            "$or": [
                {"_id": codigo_seguimiento},
                {"codigo_seguimiento": codigo_seguimiento},
            ]
        }
    )

    if paquete is None:
        return None

    asignaciones = list(
        db.asignaciones.find({"paquete_codigo": codigo_seguimiento}).sort(
            "fecha_asignacion", 1
        )
    )

    viajes = []
    inconsistencias = []
    if paquete.get("estado") == "ENTREGADO" and not asignaciones:
        inconsistencias.append("Paquete entregado sin asignaciones históricas")

    for asignacion in asignaciones:
        id_viaje = asignacion.get("viaje_id")

        if not id_viaje:
            continue

        viaje = db.viajes.find_one({"_id": id_viaje})

        if viaje is None:
            inconsistencias.append(
                f"La asignación {asignacion.get('_id')} referencia un viaje inexistente: {id_viaje}"
            )
        if viaje is not None:
            viajes.append(
                {
                    "id_viaje": id_viaje,
                    "estado": viaje.get("estado"),
                    "vehiculo": viaje.get("vehiculo_patente", viaje.get("id_vehiculo")),
                    "conductor": viaje.get("conductor_id", viaje.get("id_conductor")),
                    "ruta": viaje.get("ruta_id", viaje.get("id_ruta")),
                    "asignacion": asignacion,
                }
            )

    return {
        "codigo_seguimiento": codigo_seguimiento,
        "paquete": paquete,
        "asignaciones": asignaciones,
        "viajes": viajes,
        "inconsistencias": inconsistencias,
    }
