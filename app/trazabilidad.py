
from datetime import datetime, timedelta, timezone

from app.conexiones import (
    conectar_mongodb,
    conectar_cassandra,
    conectar_neo4j,
)

from app.repositorio_trazabilidad_mongo import (
    consultar_trazabilidad_mongo,
)

from app.repositorio_trazabilidad_cassandra import (
    consultar_telemetria_viaje,
    consultar_alertas_viaje,
)

from app.repositorio_eta_neo4j import (
    obtener_recorrido_viaje,
)

from app.periodos_trazabilidad import (
    obtener_periodo_asignacion,
    filtrar_eventos_por_periodo,
)


def obtener_dias(inicio, fin):
    """
    Devuelve todos los dias comprendidos entre dos fechas,
    incluyendo ambos extremos.

    Permite consultar viajes que duran varios dias.
    """

    if isinstance(inicio, datetime):
        inicio = inicio.date()

    if isinstance(fin, datetime):
        fin = fin.date()

    dia = inicio

    while dia <= fin:
        yield dia
        dia += timedelta(days=1)


def consultar_trazabilidad_completa(codigo_seguimiento):
    """
    CU-08: Trazabilidad completa de un paquete.

    Recibe un codigo de seguimiento y consulta:

    1. MongoDB:
       - Datos del paquete.
       - Asignaciones historicas.
       - Viajes, vehiculos y conductores.

    2. Cassandra:
       - Posiciones GPS de cada viaje.
       - Alertas historicas de cada viaje.
       - Consulta por viaje y dia, sin ALLOW FILTERING.

    3. Neo4j:
       - Recorrido planificado de cada viaje.
       - Puntos de entrega ordenados.

    Los periodos se obtienen desde MongoDB.
    Los eventos se filtran segun el periodo de cada asignacion.
    """

    if not isinstance(codigo_seguimiento, str):
        raise ValueError(
            "El codigo de seguimiento debe ser un texto"
        )

    codigo_seguimiento = codigo_seguimiento.strip()

    if not codigo_seguimiento:
        raise ValueError(
            "El codigo de seguimiento no puede estar vacio"
        )

    cliente_mongo = None
    cluster_cassandra = None
    driver_neo4j = None

    try:
        # ==========================================
        # PASO 1: CONSULTAR MONGODB
        # ==========================================

        cliente_mongo = conectar_mongodb()

        resultado_mongo = consultar_trazabilidad_mongo(
            cliente_mongo,
            codigo_seguimiento
        )

        if resultado_mongo is None:
            return {
                "exito": False,
                "codigo_seguimiento": codigo_seguimiento,
                "error": "Paquete no encontrado en MongoDB",
            }

        # ==========================================
        # PASO 2: CONECTAR CASSANDRA Y NEO4J
        # ==========================================

        cluster_cassandra, sesion_cassandra = (
            conectar_cassandra()
        )

        driver_neo4j = conectar_neo4j()

        viajes_completos = []

        # ==========================================
        # PASO 3: PROCESAR CADA VIAJE DEL PAQUETE
        # ==========================================

        for viaje in resultado_mongo["viajes"]:

            viaje_id = viaje["id_viaje"]

            asignacion = viaje["asignacion"]

            # Obtener las fechas reales de la asignacion.
            inicio, fin = obtener_periodo_asignacion(
                asignacion
            )

            # Evitar consultar fechas futuras.
            ahora = datetime.now(timezone.utc)
            fin_consulta = min(
                fin if fin is not None else ahora,
                ahora
            )

            posiciones = []
            alertas = []

            # ======================================
            # PASO 4: CONSULTAR CASSANDRA
            # ======================================

            if inicio <= fin_consulta:

                for dia in obtener_dias(
                    inicio.date(),
                    fin_consulta.date()
                ):

                    posiciones_dia = (
                        consultar_telemetria_viaje(
                            sesion_cassandra,
                            viaje_id,
                            dia
                        )
                    )

                    alertas_dia = consultar_alertas_viaje(
                        sesion_cassandra,
                        viaje_id,
                        dia
                    )

                    posiciones.extend(posiciones_dia)
                    alertas.extend(alertas_dia)

            # Filtrar eventos por periodo de asignacion.
            posiciones = filtrar_eventos_por_periodo(
                posiciones,
                inicio,
                fin_consulta
            )

            alertas = filtrar_eventos_por_periodo(
                alertas,
                inicio,
                fin_consulta
            )

            # ======================================
            # PASO 5: CONSULTAR NEO4J
            # ======================================

            recorrido = obtener_recorrido_viaje(
                driver_neo4j,
                viaje_id
            )

            # ======================================
            # PASO 6: INTEGRAR RESULTADOS
            # ======================================

            viaje_completo = {
                "viaje_id": viaje_id,

                "vehiculo": viaje["vehiculo"],

                "conductor": viaje["conductor"],

                "ruta": viaje["ruta"],

                "estado_viaje": viaje["estado"],

                "periodo_asignacion": {
                    "inicio": inicio.isoformat(),
                    "fin": (
                        fin.isoformat()
                        if fin is not None
                        else None
                    ),
                },

                "estado_asignacion": asignacion.get(
                    "estado"
                ),

                "punto_inicio": asignacion.get(
                    "punto_inicio_id"
                ),

                "punto_fin": asignacion.get(
                    "punto_fin_id"
                ),

                "recorrido": recorrido,

                "posiciones_gps": posiciones,

                "alertas": alertas,

                "total_posiciones": len(posiciones),

                "total_alertas": len(alertas),
            }

            viajes_completos.append(viaje_completo)

        # ==========================================
        # PASO 7: ORDENAR Y CONSOLIDAR
        # ==========================================

        viajes_completos.sort(
            key=lambda v: v["periodo_asignacion"]["inicio"]
        )

        total_posiciones = sum(
            viaje["total_posiciones"]
            for viaje in viajes_completos
        )

        total_alertas = sum(
            viaje["total_alertas"]
            for viaje in viajes_completos
        )

        # ==========================================
        # RESULTADO FINAL DEL CU-08
        # ==========================================

        return {
            "exito": True,

            "codigo_seguimiento": codigo_seguimiento,

            "estado_paquete": resultado_mongo[
                "paquete"
            ].get("estado"),

            "total_viajes": len(viajes_completos),

            "total_posiciones_gps": total_posiciones,

            "total_alertas": total_alertas,

            "viajes": viajes_completos,
        }

    finally:
        # ==========================================
        # CERRAR CONEXIONES
        # ==========================================

        if driver_neo4j is not None:
            driver_neo4j.close()

        if cluster_cassandra is not None:
            cluster_cassandra.shutdown()

        if cliente_mongo is not None:
            cliente_mongo.close()
