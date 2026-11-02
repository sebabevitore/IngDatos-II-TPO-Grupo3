"""Demostraciones verificables que dejan entidades completas para CU08."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from app.demo_comun import (
    motores,
    crear_escenario,
    emitir,
    comprobar,
    guardar_resultado,
    valor_redis,
)


def comprobar_evento(e, d):
    documento = e.mongo["logistica"].eventos_telemetria.find_one(
        {"_id": d["id_evento"]}
    )
    comprobar(
        documento
        and documento["estado_procesamiento"] == "COMPLETADO"
        and documento["cassandra_guardado"]
        and documento["redis_procesado"],
        "Evento CU02 incompleto",
    )
    fecha = datetime.fromisoformat(d["fecha_hora"]).astimezone(timezone.utc)
    for tabla, campo, valor in (
        ("telemetria_por_viaje_dia", "viaje_id", d["viaje_id"]),
        ("telemetria_por_vehiculo_dia", "vehiculo_patente", d["vehiculo_patente"]),
    ):
        fila = e.cql.execute(
            f"SELECT * FROM logistica_flota.{tabla} WHERE {campo}=%s AND dia=%s AND fecha_hora=%s AND id_evento=%s",
            (valor, fecha.date(), fecha.replace(tzinfo=None), UUID(d["id_evento"])),
        ).one()
        comprobar(
            fila and fila.velocidad == d["velocidad"] and fila.latitud == d["latitud"],
            "Falta una medición en Cassandra",
        )


def trazabilidad(codigo):
    from app.trazabilidad import consultar_trazabilidad_completa

    resultado = consultar_trazabilidad_completa(codigo)
    comprobar(
        resultado.get("exito") and resultado["total_viajes"] > 0,
        "La operación no conserva trazabilidad",
    )
    comprobar(
        all(v["recorrido"] for v in resultado["viajes"]),
        "Falta recorrido en algún tramo de la trazabilidad",
    )
    return resultado


def cu01_feliz():
    from app.coordinador_viajes import planificar_viaje

    with motores() as e:
        f = crear_escenario(e, "CU01", activo=False)
        datos = dict(
            id_ruta=f["ruta"],
            id_vehiculo=f["vehiculos"][0],
            id_conductor=f["conductores"][0],
            paquetes=f["paquetes"],
        )
        ok, r = planificar_viaje(e.redis, e.db.viajes, datos, driver_neo4j=e.neo)
        comprobar(ok, str(r))
        f["viaje"] = r["id_viaje"]
        comprobar(
            e.db.viajes.find_one({"_id": f["viaje"]}) is not None,
            "No persistió el viaje",
        )
        comprobar(
            e.db.asignaciones.count_documents(
                {"viaje_id": f["viaje"], "estado": "ACTIVA"}
            )
            == len(f["paquetes"]),
            "Faltan asignaciones",
        )
        comprobar(
            e.redis.ttl(f'reserva:vehiculo:{f["vehiculos"][0]}') == -1,
            "Reserva no confirmada",
        )
        t = trazabilidad(f["paquetes"][0])
        return guardar_resultado(
            "CU01",
            "planificacion_persistente",
            f,
            r,
            [
                "Viaje persistente en logistica_flota",
                "Asignaciones únicas",
                "Reserva persistente",
                "Recorrido consultable en CU08",
            ],
        )


def cu01_concurrencia():
    from app.coordinador_viajes import planificar_viaje

    with motores() as e:
        f = crear_escenario(e, "CU01-CONC", activo=False)
        datos = dict(
            id_ruta=f["ruta"],
            id_vehiculo=f["vehiculos"][0],
            id_conductor=f["conductores"][0],
            paquetes=f["paquetes"],
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    planificar_viaje, e.redis, e.db.viajes, datos, driver_neo4j=e.neo
                )
                for _ in range(2)
            ]
            respuestas = [x.result() for x in futures]
        comprobar(
            sum(ok for ok, _ in respuestas) == 1, "No hubo exactamente un ganador"
        )
        f["viaje"] = next(r["id_viaje"] for ok, r in respuestas if ok)
        comprobar(
            e.db.asignaciones.count_documents(
                {"paquete_codigo": {"$in": f["paquetes"]}, "estado": "ACTIVA"}
            )
            == len(f["paquetes"]),
            "Asignaciones duplicadas",
        )
        return guardar_resultado(
            "CU01",
            "concurrencia_viaje",
            f,
            respuestas,
            ["Un ganador", "Sin doble asignación", "Viaje del ganador persistente"],
        )


def cu01_falla(punto="CU01_MONGO"):
    from app.coordinador_viajes import planificar_viaje
    from app.fallas import InyectorFallas

    with motores() as e:
        f = crear_escenario(e, "CU01-FALLA", activo=False)
        datos = dict(
            id_ruta=f["ruta"],
            id_vehiculo=f["vehiculos"][0],
            id_conductor=f["conductores"][0],
            paquetes=f["paquetes"],
        )
        ok, r = planificar_viaje(
            e.redis,
            e.db.viajes,
            datos,
            driver_neo4j=e.neo,
            inyector=InyectorFallas(punto),
        )
        comprobar(
            not ok and punto in str(r) and r["compensado"],
            "No se verificó la falla controlada",
        )
        comprobar(
            e.db.viajes.find_one({"_id": r["id_viaje"]}) is None, "Quedó viaje parcial"
        )
        comprobar(
            e.db.asignaciones.count_documents({"viaje_id": r["id_viaje"]}) == 0,
            "Quedaron asignaciones",
        )
        comprobar(
            all(
                e.db.paquetes.find_one({"_id": p})["estado"] == "PENDIENTE"
                for p in f["paquetes"]
            ),
            "Paquete no restaurado",
        )
        comprobar(
            e.db.vehiculos.find_one({"_id": f["vehiculos"][0]})["estado"]
            == "DISPONIBLE",
            "Vehículo no restaurado",
        )
        for tipo, valor in (
            ("vehiculo", f["vehiculos"][0]),
            ("conductor", f["conductores"][0]),
        ):
            comprobar(
                not e.redis.exists(f"reserva:{tipo}:{valor}"), "Quedó una reserva"
            )
        with e.neo.session() as s:
            comprobar(
                s.run(
                    "MATCH (v:Viaje {viaje_id:$id}) RETURN count(v) AS c",
                    id=r["id_viaje"],
                ).single()["c"]
                == 0,
                "Quedó viaje en Neo4j",
            )
        return guardar_resultado(
            "CU01",
            "rollback_" + punto,
            f,
            r,
            [
                "Falla seleccionada detectada",
                "MongoDB sin viaje ni asignaciones parciales",
                "Neo4j sin viaje parcial",
                "Recursos liberados",
            ],
        )


def cu02_actual():
    with motores() as e:
        f = crear_escenario(e, "CU02")
        d, r = emitir(f, 45.5)
        comprobar_evento(e, d)
        estado = e.redis.hgetall(f'vehiculo:{f["vehiculos"][0]}:estado')
        comprobar(
            estado["velocidad"] == "45.5" and estado["viaje_id"] == f["viaje"],
            "Redis no refleja la última medición",
        )
        return guardar_resultado(
            "CU02",
            "ingesta_actual",
            f,
            r,
            [
                "Evento MongoDB COMPLETADO",
                "Dos históricos Cassandra",
                "Redis actualizado",
            ],
        )


def cu02_antigua():
    with motores() as e:
        f = crear_escenario(e, "CU02-ORDEN")
        nuevo, _ = emitir(f, 45.5)
        antes = e.redis.hgetall(f'vehiculo:{f["vehiculos"][0]}:estado')
        viejo, r = emitir(
            f, 20.0, instante=datetime.now(timezone.utc) - timedelta(minutes=1)
        )
        comprobar_evento(e, viejo)
        comprobar(
            e.redis.hgetall(f'vehiculo:{f["vehiculos"][0]}:estado') == antes
            and not r["estado_actualizado_en_redis"],
            "La lectura antigua pisó la actual",
        )
        return guardar_resultado(
            "CU02",
            "orden_temporal_independiente",
            f,
            r,
            [
                "La demo prepara su propio estado reciente",
                "Histórico antiguo conservado",
                "Redis no retrocede",
            ],
        )


def cu03(escenario):
    from app.anomalias import procesar_anomalias_telemetria
    from app.fallas import InyectorFallas
    from app.recuperacion_anomalias import reconciliar_anomalias

    with motores() as e:
        f = crear_escenario(e, "CU03")
        patente = f["vehiculos"][0]
        clave = f"alerta:activa:{patente}:EXCESO_VELOCIDAD"
        d, _ = emitir(f, 105.0)
        if escenario == 3:
            try:
                procesar_anomalias_telemetria(
                    d, inyector=InyectorFallas("CASSANDRA_WRITE")
                )
            except Exception as error:
                comprobar(
                    "CASSANDRA_WRITE" in str(error), "No ocurrió la falla esperada"
                )
            else:
                raise RuntimeError("No se produjo la falla")
            comprobar(not e.redis.exists(clave), "Quedó claim en Redis")
            comprobar(
                not list(
                    e.cql.execute(
                        "SELECT * FROM logistica_flota.alertas_abiertas_por_vehiculo WHERE vehiculo_patente=%s",
                        (patente,),
                    )
                ),
                "Quedó alerta abierta",
            )
            r = dict(falla="CASSANDRA_WRITE", compensado=True)
        elif escenario == 4:
            try:
                procesar_anomalias_telemetria(
                    d, inyector=InyectorFallas("REDIS_CONFIRM")
                )
            except Exception as error:
                comprobar("REDIS_CONFIRM" in str(error), "No ocurrió la falla esperada")
            else:
                raise RuntimeError("No se produjo la falla")
            r = reconciliar_anomalias(patentes=[patente])
            comprobar(
                e.redis.hget(clave, "estado") == "ACTIVE", "Reconciliación no confirmó"
            )
        else:
            r = procesar_anomalias_telemetria(d)
            id_activa = e.redis.hget(clave, "alerta_id")
            comprobar(
                id_activa and e.redis.hget(clave, "estado") == "ACTIVE",
                "Falta alerta activa",
            )
            if escenario == 2:
                respuestas = []
                for i in range(5):
                    lectura, _ = emitir(f, 110.0 + i)
                    respuesta = procesar_anomalias_telemetria(lectura)
                    comprobar(
                        respuesta["anomalias_detectadas"][0]["alerta_id"] == id_activa,
                        "La deduplicación devolvió otro ID",
                    )
                    respuestas.append(respuesta)
                r = respuestas
                filas = list(
                    e.cql.execute(
                        "SELECT alerta_id FROM logistica_flota.alertas_por_viaje_dia WHERE viaje_id=%s AND dia=%s",
                        (f["viaje"], datetime.now(timezone.utc).date()),
                    )
                )
                comprobar(
                    len(filas) == 1 and str(filas[0].alerta_id) == id_activa,
                    "Se duplicó la alerta histórica",
                )
            if escenario == 5:
                # Pérdida controlada solo de la clave de ESTA fixture. No FLUSHALL.
                claves = set(e.redis.scan_iter("*"))
                otras = {
                    k: valor_redis(e.redis, k)
                    for k in claves
                    if not k.startswith("alerta:activa:")
                }
                e.redis.eval(
                    "if redis.call('HGET',KEYS[1],'alerta_id')==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                    1,
                    clave,
                    id_activa,
                )
                r = reconciliar_anomalias(patentes=[patente])
                comprobar(
                    e.redis.hget(clave, "alerta_id") == id_activa,
                    "No se reconstruyó la alerta durable",
                )
                comprobar(
                    all(valor_redis(e.redis, k) == v for k, v in otras.items()),
                    "Se modificaron claves ajenas a la alerta",
                )
        return guardar_resultado(
            "CU03",
            str(escenario),
            f,
            r,
            [
                "Alerta/compensación contrastada con Cassandra y Redis",
                "Sin borrado global ni claves de otros vehículos",
            ],
        )


def cu04(escenario):
    from app.eta import calcular_eta_y_desvio

    with motores() as e:
        f = crear_escenario(e, "CU04")
        if escenario == 1:
            for i, duracion in enumerate((10.0, 20.0)):
                e.cql.execute(
                    "INSERT INTO logistica_flota.tiempos_tramo_historico (tramo_id,fecha_hora,viaje_id,duracion_minutos) VALUES (%s,%s,%s,%s)",
                    (
                        f["tramo"],
                        datetime.now(timezone.utc).replace(tzinfo=None)
                        - timedelta(seconds=i + 1),
                        f["viaje"],
                        duracion,
                    ),
                )
        lat, lon = (
            (-34.61, -58.42)
            if escenario == 3
            else (-34.615, -58.39) if escenario == 2 else (-34.601, -58.401)
        )
        d, _ = emitir(f, latitud=lat, longitud=lon)
        comprobar_evento(e, d)
        r = calcular_eta_y_desvio(f["viaje"])
        comprobar(r.get("ok"), str(r))
        comprobar(r["desviado"] == (escenario == 2), "Detección de desvío incorrecta")
        comprobar(
            r["fuente_eta"] == ("historico" if escenario == 1 else "planificado"),
            "No se consultó la fuente ETA esperada",
        )
        # Invariantes funcionales: tiempo restante, agenda presente y sensibilidad
        # al histórico. La fórmula también tiene pruebas unitarias independientes.
        comprobar(
            0 <= r["eta_minutos"] <= 30, "ETA restante fuera del rango de la fixture"
        )
        comprobar(r["hora_planificada"] is not None, "Falta horario previsto")
        comprobar(
            r["base_planificada"] == "horarios_paradas",
            "No se usó la agenda de paradas",
        )
        if escenario == 1:
            comprobar(
                abs(r["eta_minutos"] - 9.6) < 0.15,
                "El histórico no modifica la duración restante esperada",
            )
        if escenario == 3:
            comprobar(
                r["proximo_punto"] == f["puntos"][2]
                and abs(r["eta_minutos"] - 8.8) < 0.1,
                "En la parada intermedia no se calculó el siguiente tramo",
            )
        return guardar_resultado(
            "CU04",
            str(escenario),
            f,
            r,
            [
                "Redis y recorrido propios",
                "Histórico real o fallback comprobado",
                "Desvío verificado",
            ],
        )


def cu05(escenario):
    from app.reasignacion import reasignar_por_averia
    from app.fallas import InyectorFallas

    with motores() as e:
        f = crear_escenario(e, "CU05")
        emitir(f)
        datos = dict(
            id_viaje_averiado=f["viaje"],
            patente_averiada=f["vehiculos"][0],
            patente_reemplazo=f["vehiculos"][1],
            conductor_reemplazo=f["conductores"][1],
            id_punto_averia=f["puntos"][0],
            puntos_destino=[f["puntos"][2]],
        )
        if escenario == 2:
            otro = crear_escenario(e, "CU05-OTRO")
            emitir(otro)
            # Ambos rescates deben llegar a sus destinos: unir las redes solo en el punto de avería.
            otro_dato = dict(
                id_viaje_averiado=otro["viaje"],
                patente_averiada=otro["vehiculos"][0],
                patente_reemplazo=f["vehiculos"][1],
                conductor_reemplazo=f["conductores"][1],
                id_punto_averia=otro["puntos"][0],
                puntos_destino=[otro["puntos"][2]],
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                respuestas = [
                    pool.submit(reasignar_por_averia, x) for x in (datos, otro_dato)
                ]
                r = [x.result() for x in respuestas]
            comprobar(
                sum(x["exito"] for x in r) == 1,
                "La concurrencia no tuvo un ganador único",
            )
            for viaje, pk in (
                (f["viaje"], f["paquetes"]),
                (otro["viaje"], otro["paquetes"]),
            ):
                for codigo in pk:
                    comprobar(
                        e.db.asignaciones.count_documents(
                            {"paquete_codigo": codigo, "estado": "ACTIVA"}
                        )
                        == 1,
                        "Paquete sin asignación o duplicado",
                    )
        else:
            punto = {
                3: "CU05_NEO4J",
                4: "CU05_MONGO",
                5: "CU05_REDIS_CONFIRM",
                6: "CU05_PAQUETES",
            }.get(escenario)
            r = reasignar_por_averia(
                datos, inyector=InyectorFallas(punto) if punto else None
            )
            if punto:
                comprobar(
                    not r["exito"] and punto in str(r),
                    "No se detectó la falla solicitada",
                )
                for tipo, valor in (
                    ("vehiculo", f["vehiculos"][1]),
                    ("conductor", f["conductores"][1]),
                ):
                    comprobar(
                        not e.redis.exists(f"reserva:{tipo}:{valor}"),
                        "Quedó reserva del rescate",
                    )
                comprobar(
                    e.db.asignaciones.count_documents(
                        {"viaje_id": f["viaje"], "estado": "ACTIVA"}
                    )
                    == len(f["paquetes"]),
                    "No se conservaron asignaciones",
                )
            else:
                comprobar(r["exito"], str(r))
                nuevo = r["id_viaje_rescate"]
                emitir(f, viaje=nuevo, vehiculo=f["vehiculos"][1])
                comprobar(
                    e.db.asignaciones.count_documents(
                        {"viaje_id": f["viaje"], "estado": "INTERRUMPIDA"}
                    )
                    == len(f["paquetes"]),
                    "Falta historia original",
                )
                comprobar(
                    e.db.asignaciones.count_documents(
                        {"viaje_id": nuevo, "estado": "ACTIVA"}
                    )
                    == len(f["paquetes"]),
                    "Faltan asignaciones de rescate",
                )
                comprobar(
                    e.redis.ttl(f'reserva:vehiculo:{f["vehiculos"][1]}') == -1,
                    "El rescate quedó sin reserva persistente",
                )
                t = trazabilidad(f["paquetes"][0])
                comprobar(
                    t["total_viajes"] == 2 and t["total_posiciones_gps"] >= 2,
                    "CU08 no traza ambos tramos",
                )
        return guardar_resultado(
            "CU05",
            str(escenario),
            f,
            r,
            [
                "Paquetes maestros existentes",
                "Una asignación activa por paquete",
                "Historia preservada",
                "Recursos y grafo comprobados",
            ],
        )


def cu06(escenario):
    from app.entrega import confirmar_entrega_paquete
    from app.fallas import InyectorFallas

    with motores() as e:
        f = crear_escenario(e, "CU06", paquetes=1)
        emitir(f)
        datos = dict(
            viaje_id=f["viaje"],
            paquete_codigo=f["paquetes"][0],
            vehiculo_patente=f["vehiculos"][0],
            fecha_hora=datetime.now(timezone.utc).isoformat(),
            receptor_nombre="Receptor de demostración",
            receptor_dni="00000000",
            receptor_vinculo="TITULAR",
            latitud=-34.63,
            longitud=-58.45,
        )
        punto = {3: "CU06_CASSANDRA", 4: "CU06_MONGO", 5: "CU06_REDIS_CONFIRM"}.get(
            escenario
        )
        if escenario == 2:
            with ThreadPoolExecutor(max_workers=2) as pool:
                r = [
                    x.result()
                    for x in [
                        pool.submit(confirmar_entrega_paquete, dict(datos))
                        for _ in range(2)
                    ]
                ]
            comprobar(sum(x["exito"] for x in r) == 1, "No hubo un único ganador")
        else:
            r = confirmar_entrega_paquete(
                datos, inyector=InyectorFallas(punto) if punto else None
            )
        filas = list(
            e.cql.execute(
                "SELECT * FROM logistica_flota.confirmaciones_entrega_por_viaje_dia WHERE viaje_id=%s AND dia=%s",
                (f["viaje"], datetime.now(timezone.utc).date()),
            )
        )
        paquete = e.db.paquetes.find_one({"_id": f["paquetes"][0]})
        if punto:
            comprobar(
                not r["exito"] and punto in str(r), "No se produjo la falla esperada"
            )
            comprobar(
                paquete["estado"] == "EN_TRANSITO" and not filas,
                "Entrega parcial después del rollback",
            )
            comprobar(
                not e.redis.exists(f'lock:entrega:paquete:{f["paquetes"][0]}'),
                "Quedó lock de entrega",
            )
        else:
            comprobar(
                (isinstance(r, list) or r["exito"])
                and paquete["estado"] == "ENTREGADO"
                and len(filas) == 1,
                "Entrega inconsistente",
            )
            progreso = e.redis.hgetall(f'viaje:{f["viaje"]}:progreso')
            comprobar(
                progreso["entregas_completadas"] == "1"
                and progreso["entregas_pendientes"] == "0",
                "Métricas incompatibles",
            )
            repeticion = confirmar_entrega_paquete(dict(datos))
            comprobar(
                not repeticion["exito"],
                "Se aceptó una segunda entrega del mismo paquete",
            )
            comprobar(
                len(
                    list(
                        e.cql.execute(
                            "SELECT * FROM logistica_flota.confirmaciones_entrega_por_viaje_dia WHERE viaje_id=%s AND dia=%s",
                            (f["viaje"], datetime.now(timezone.utc).date()),
                        )
                    )
                )
                == 1,
                "El reintento duplicó POD",
            )
            t = trazabilidad(f["paquetes"][0])
            comprobar(
                t["total_posiciones_gps"] >= 1, "Falta GPS para trazabilidad de entrega"
            )
        return guardar_resultado(
            "CU06",
            str(escenario),
            f,
            r,
            [
                "Viaje y recorrido existentes",
                "POD y contadores contrastados",
                "Sin reiniciar el paquete al reintentar",
                "CU08 disponible",
            ],
        )


def cu07(escenario):
    from app.rutas_alternativas import consultar_impacto_y_alternativa

    with motores() as e:
        f = crear_escenario(e, "CU07", alternativa=escenario == 1)
        emitir(f)
        antes = e.redis.hgetall(f'vehiculo:{f["vehiculos"][0]}:estado')
        r = consultar_impacto_y_alternativa(
            f["puntos"][0], f["puntos"][2], f["puntos"][1]
        )
        comprobar(r.get("exito"), str(r))
        if escenario == 1:
            comprobar(
                r["alternativa"]["recorrido"]
                == [f["puntos"][0], f["puntos"][3], f["puntos"][2]],
                "Desvío incorrecto",
            )
            comprobar(
                any(
                    v["viaje_id"] == f["viaje"] and v["en_circulacion"]
                    for item in r["impacto"]
                    for v in item["viajes_afectados"]
                ),
                "No se cruzó Redis con el viaje afectado",
            )
        else:
            comprobar(
                isinstance(r["alternativa"], str) and "No existe" in r["alternativa"],
                "La red de esta demo todavía tiene salida",
            )
        comprobar(
            e.redis.hgetall(f'vehiculo:{f["vehiculos"][0]}:estado') == antes,
            "La consulta pisó un estado del vehículo",
        )
        return guardar_resultado(
            "CU07",
            str(escenario),
            f,
            r,
            [
                "Red exclusiva para esta demo",
                "Bloqueo real en la consulta",
                "Sin sobrescribir estados compartidos",
            ],
        )


def cu02_simulacion():
    """Acceso al simulador existente, también disponible desde la consola unificada."""
    import json
    from pathlib import Path
    from app.simular_telemetria import main

    ident = "DEMO-CU02-SIM-" + uuid4().hex[:12]
    carpeta = Path("resultados_menus") / "simulaciones" / ident
    print("Se enviarán lecturas reales a 50 vehículos con viajes EN_CURSO existentes.")
    comprobar(
        main(["--salida", str(carpeta)]) == 0,
        "No se verificó la simulación de los 50 vehículos",
    )
    plan = json.loads((carpeta / "plan.json").read_text())
    reporte = json.loads((carpeta / "resumen.json").read_text())
    f = dict(
        demo_id=ident,
        paquetes=[],
        vehiculos=[p["vehiculo_patente"] for p in plan["participantes"]],
        viajes=[p["viaje_id"] for p in plan["participantes"]],
        carpeta_simulacion=str(carpeta),
    )
    return guardar_resultado(
        "CU02",
        "simulacion_50",
        f,
        reporte,
        [
            "50 emisores y 250 mediciones reales",
            "Concurrencia y persistencia verificadas por CU02",
        ],
    )
