"""CU01/CU05/CU06 con intención durable previa y compensación recuperable.

MongoDB es autoridad del negocio y de sus métricas; Redis es una proyección.
Los lectores detectan recursos en saga para no publicar estados intermedios.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5, NAMESPACE_URL
from app.operaciones import Saga, ahora
from app.tiempos import utc, intervalo, validar_disponibilidad, paradas_planificadas
from app.repositorio_rutas_neo4j import vincular_viaje_ruta_neo4j, compensar_viaje_neo4j
from app.repositorio_reasignacion_neo4j import (
    vincular_rescate_neo4j,
    compensar_rescate_neo4j,
)
from app.repositorio_entrega_cassandra import (
    registrar_entrega_cassandra,
    compensar_entrega_cassandra,
)


def _inicio(db, tipo, datos):
    saga = Saga(db, tipo, datos)
    if saga.propia:
        return saga, None
    if saga.doc["estado"] == "COMPLETADO" and (
        datos.get("id_operacion") or datos.get("clave_idempotencia")
    ):
        return saga, dict(saga.doc["resultado"], repetida=True)
    return saga, dict(
        exito=False,
        saga_id=saga.id,
        id_operacion=saga.id,
        estado=saga.doc["estado"],
        duplicada=True,
        error="Solicitud ya registrada; consultar resultado o ejecutar recuperación",
    )


def _reserva(redis, clave, saga):
    script = """
    local v=redis.call('GET',KEYS[1])
    if v and v~=ARGV[1] then return 0 end
    redis.call('SET',KEYS[1],ARGV[1]); return 1
    """
    if redis.eval(script, 1, clave, saga.id) != 1:
        raise RuntimeError(f"Recurso Redis ocupado: {clave}")


def _soltar(redis, clave, ident):
    redis.eval(
        "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
        1,
        clave,
        ident,
    )


def _guardar_proyecciones(saga, redis, claves_campos):
    fotos = []
    for clave, campos in claves_campos:
        foto = redis.hgetall(clave)
        fotos.append(
            dict(
                clave=clave,
                campos=campos,
                antes={k: foto[k] for k in campos if k in foto},
            )
        )
    saga.guardar(redis_antes=fotos)


def _proyectar(saga, redis, clave, campos):
    saga.exigir_propiedad()
    redis.hset(clave, mapping=dict(campos, operacion_estado=saga.id))


def _restaurar_redis(saga, redis):
    # Restaurar solo campos operativos, nunca borrar posiciones GPS posteriores.
    script = """
    if redis.call('HGET',KEYS[1],'operacion_estado')~=ARGV[1] then return 0 end
    for i=2,#ARGV,2 do
      if ARGV[i+1]=='__AUSENTE__' then redis.call('HDEL',KEYS[1],ARGV[i])
      else redis.call('HSET',KEYS[1],ARGV[i],ARGV[i+1]) end
    end
    redis.call('HDEL',KEYS[1],'operacion_estado');return 1
    """
    for foto in saga.doc.get("redis_antes", []):
        args = [saga.id]
        for campo in foto["campos"]:
            args.extend([campo, foto["antes"].get(campo, "__AUSENTE__")])
        redis.eval(script, 1, foto["clave"], *args)
    for clave in saga.doc.get("reservas_redis", []):
        _soltar(redis, clave, saga.id)


def compensar(saga, redis, neo=None, cql=None, error="Interrupción del ejecutor"):
    pasos = saga.doc.get("pasos", [])
    acciones = []
    if saga.doc["tipo"] == "ENTREGA" and "CU06_CASSANDRA" in pasos:
        d = saga.doc["entrega"]
        f = utc(d["fecha_hora"])
        acciones.append(
            (
                "CASSANDRA",
                lambda: compensar_entrega_cassandra(
                    cql,
                    d["viaje_id"],
                    f.date(),
                    f.replace(tzinfo=None),
                    d["paquete_codigo"],
                ),
            )
        )
    # Las fotografías también revierten una escritura cuyo ACK se perdió.
    acciones.append(("MONGODB", saga.restaurar_mongo))
    if saga.doc["tipo"] == "PLANIFICACION" and "CU01_NEO4J" in pasos:
        acciones.append(
            ("NEO4J", lambda: compensar_viaje_neo4j(neo, saga.doc["viaje_id"]))
        )
    if saga.doc["tipo"] == "REASIGNACION" and "CU05_NEO4J" in pasos:
        acciones.append(
            (
                "NEO4J",
                lambda: compensar_rescate_neo4j(
                    neo,
                    saga.doc["viaje_rescate"],
                    saga.doc["datos"]["id_viaje_averiado"],
                ),
            )
        )
    acciones.append(("REDIS", lambda: _restaurar_redis(saga, redis)))
    return saga.compensar(acciones, error)


def planificar(redis, db, datos, neo, inyector=None):
    saga, res = _inicio(db, "PLANIFICACION", datos)
    if res is not None:
        return res
    viaje = str(uuid5(NAMESPACE_URL, saga.id))
    saga.guardar(viaje_id=viaje)
    try:
        v, c = datos["id_vehiculo"], datos["id_conductor"]
        paquetes = datos["paquetes"]
        saga.bloquear(
            [f"viaje:{viaje}", f"vehiculo:{v}", f"conductor:{c}"]
            + [f"paquete:{p}" for p in paquetes]
        )
        inicio, fin = intervalo(datos, saga.doc["fecha_inicio"])
        validar_disponibilidad(db, v, c, inicio, fin)
        with neo.session() as ses:
            puntos = [
                r["id"]
                for r in ses.run(
                    "MATCH (r:Ruta {ruta_id:$ruta,estado:'HABILITADA'})-[i:INCLUYE]->(p:PuntoEntrega) RETURN p.punto_entrega_id AS id ORDER BY i.orden",
                    ruta=datos["id_ruta"],
                )
            ]
        if len(puntos) < 2:
            raise ValueError("Ruta no habilitada o recorrido insuficiente")
        paradas = paradas_planificadas(puntos, datos, inicio, fin)
        usuario = datos.get("planificado_por_usuario_id")
        if not usuario:
            ruta = db.rutas.find_one({"_id": datos["id_ruta"]}) or {}
            usuario = ruta.get("planificada_por_usuario_id")
        if not usuario or not db.usuarios.find_one({"_id": usuario}):
            raise ValueError("Debe indicar un usuario coordinador existente")
        for p in paquetes:
            doc = db.paquetes.find_one({"_id": p, "estado": "PENDIENTE"})
            if not doc or doc.get("punto_entrega_id") not in puntos:
                raise ValueError("Paquete no pendiente o destino ajeno al recorrido")
            if db.asignaciones.find_one({"paquete_codigo": p, "estado": "ACTIVA"}):
                raise ValueError("El paquete ya tiene asignación activa")
        reservas = [
            f"agenda:{tipo}:{ident}:{saga.id}"
            for tipo, ident in [("vehiculo", v), ("conductor", c)]
        ]
        # Compatibilidad: la clave simple muestra la primera reserva; la agenda durable
        # en MongoDB controla intervalos y admite otros viajes no superpuestos.
        for tipo, ident in [("vehiculo", v), ("conductor", c)]:
            clave = f"reserva:{tipo}:{ident}"
            if not redis.exists(clave):
                reservas.append(clave)
        saga.guardar(reservas_redis=reservas)
        saga.paso(
            "CU01_REDIS_RESERVA",
            lambda: [_reserva(redis, k, saga) for k in reservas],
            inyector,
        )
        saga.paso(
            "CU01_NEO4J",
            lambda: vincular_viaje_ruta_neo4j(neo, viaje, datos["id_ruta"], v, c),
            inyector,
        )
        saga.snapshot("viajes", [viaje])
        saga.snapshot("paquetes", paquetes)
        asigs = [f"ASIG-{viaje}-{p}" for p in paquetes]
        saga.snapshot("asignaciones", asigs)

        def negocio():
            saga.cambiar(
                "viajes",
                viaje,
                dict(
                    id_operacion=saga.id,
                    ruta_id=datos["id_ruta"],
                    id_ruta=datos["id_ruta"],
                    vehiculo_patente=v,
                    id_vehiculo=v,
                    conductor_id=c,
                    id_conductor=c,
                    planificado_por_usuario_id=usuario,
                    inicio_planificado=inicio,
                    fin_planificado=fin,
                    paradas=paradas,
                    paquetes=paquetes,
                    estado="PLANIFICADO",
                    fecha_creacion=ahora(),
                    entregas_completadas=0,
                    entregas_pendientes=len(paquetes),
                    demora_acumulada_min=0,
                ),
            )
            for p, a in zip(paquetes, asigs):
                doc = db.paquetes.find_one({"_id": p})
                saga.cambiar(
                    "asignaciones",
                    a,
                    dict(
                        viaje_id=viaje,
                        paquete_codigo=p,
                        punto_inicio_id=puntos[0],
                        punto_fin_id=doc["punto_entrega_id"],
                        estado="ACTIVA",
                        fecha_asignacion=inicio,
                        creada_por_usuario_id=usuario,
                    ),
                )
                saga.cambiar(
                    "paquetes", p, dict(estado="ASIGNADO", viaje_actual_id=viaje)
                )
                if inyector:
                    inyector.verificar("CU01_PAQUETES")

        saga.paso("CU01_MONGO", negocio, inyector)
        saga.paso(
            "CU01_REDIS_CONFIRM",
            lambda: [_reserva(redis, k, saga) for k in reservas],
            inyector,
        )
        return saga.completar(
            dict(
                exito=True,
                id_viaje=viaje,
                id_operacion=saga.id,
                estado="PLANIFICADO",
                neo4j_vinculado=True,
                asignaciones=len(paquetes),
            )
        )
    except Exception as exc:
        return dict(compensar(saga, redis, neo, error=exc), id_viaje=viaje)


def _metricas(db, viaje_id):
    asignaciones = list(
        db.asignaciones.find(
            {"viaje_id": viaje_id, "estado": {"$in": ["ACTIVA", "COMPLETADA"]}}
        )
    )
    completas = [a for a in asignaciones if a["estado"] == "COMPLETADA"]
    # Una parada puede recibir varios paquetes: la demora de parada se cuenta una vez.
    demora = sum(
        float(p.get("demora_min", 0))
        for p in (db.viajes.find_one({"_id": viaje_id}) or {}).get("paradas", [])
    )
    return dict(
        entregas_completadas=len(completas),
        entregas_pendientes=len(asignaciones) - len(completas),
        demora_acumulada_min=round(demora, 3),
    )


def entregar(redis, db, cql, datos, inyector=None):
    saga, res = _inicio(db, "ENTREGA", datos)
    if res is not None:
        return res
    try:
        d = dict(datos)
        d["fecha_hora"] = utc(
            d.get("fecha_hora") or saga.doc["fecha_inicio"]
        ).isoformat()
        d["id_evento"] = str(uuid5(NAMESPACE_URL, saga.id))
        p, v = d["paquete_codigo"], d["viaje_id"]
        # Intención y clave Cassandra antes de toda escritura/ACK.
        saga.guardar(entrega=d)
        saga.bloquear([f"paquete:{p}", f"viaje:{v}"])
        paquete = db.paquetes.find_one({"_id": p})
        viaje = db.viajes.find_one({"_id": v})
        asignacion = db.asignaciones.find_one(
            {"paquete_codigo": p, "viaje_id": v, "estado": "ACTIVA"}
        )
        if (
            not paquete
            or paquete.get("estado") == "ENTREGADO"
            or not viaje
            or not asignacion
        ):
            raise ValueError(
                "Paquete entregado, inexistente o sin asignación activa en ese viaje"
            )
        if viaje.get("estado") not in ("EN_CURSO", "PLANIFICADO"):
            raise ValueError("El viaje no admite entregas")
        if d.get("vehiculo_patente") != viaje.get(
            "vehiculo_patente", viaje.get("id_vehiculo")
        ):
            raise ValueError("El vehículo no corresponde al viaje")
        claves = [
            (f"paquete:{p}:estado", ["estado", "viaje_id"]),
            (
                f"viaje:{v}:progreso",
                ["entregas_completadas", "entregas_pendientes", "demora_acumulada_min"],
            ),
        ]
        _guardar_proyecciones(saga, redis, claves)
        reserva = f"lock:entrega:paquete:{p}"
        saga.guardar(reservas_redis=[reserva])
        saga.paso("CU06_REDIS_LOCK", lambda: _reserva(redis, reserva, saga), inyector)
        saga.snapshot("paquetes", [p])
        saga.snapshot("asignaciones", [asignacion["_id"]])
        saga.snapshot("viajes", [v])
        cass = saga.paso(
            "CU06_CASSANDRA", lambda: registrar_entrega_cassandra(cql, d), inyector
        )

        def negocio():
            fecha = utc(d["fecha_hora"])
            receptor = dict(
                nombre=d.get("receptor_nombre", "Consignatario"),
                dni=d.get("receptor_dni", ""),
                vinculo=d.get("receptor_vinculo", "TITULAR"),
            )
            saga.cambiar(
                "paquetes",
                p,
                dict(estado="ENTREGADO", fecha_entrega=fecha, receptor=receptor),
            )
            saga.cambiar(
                "asignaciones",
                asignacion["_id"],
                dict(estado="COMPLETADA", fecha_fin=fecha, entregado_a=receptor),
            )
            paradas = viaje.get("paradas", [])
            for parada in paradas:
                if parada["punto_entrega_id"] == paquete.get("punto_entrega_id"):
                    # La parada se completa cuando se entregan todos sus paquetes.
                    pendientes = list(
                        db.asignaciones.find(
                            {
                                "viaje_id": v,
                                "estado": "ACTIVA",
                                "punto_fin_id": parada["punto_entrega_id"],
                            }
                        )
                    )
                    if not pendientes:
                        parada["hora_real"] = fecha
                        parada["estado"] = "COMPLETADA"
                        prevista = parada.get("hora_planificada")
                        parada["demora_min"] = (
                            max(0, (fecha - utc(prevista)).total_seconds() / 60)
                            if prevista
                            else 0
                        )
                    break
            saga.cambiar("viajes", v, dict(paradas=paradas))
            saga.cambiar("viajes", v, _metricas(db, v))

        saga.paso("CU06_MONGO", negocio, inyector)

        def proyeccion():
            _proyectar(
                saga, redis, f"paquete:{p}:estado", dict(estado="ENTREGADO", viaje_id=v)
            )
            _proyectar(saga, redis, f"viaje:{v}:progreso", _metricas(db, v))

        saga.paso("CU06_REDIS_CONFIRM", proyeccion, inyector)
        _soltar(redis, reserva, saga.id)
        return saga.completar(
            dict(
                exito=True,
                saga_id=saga.id,
                viaje_id=v,
                paquete_codigo=p,
                receptor=d.get("receptor_nombre", "Consignatario"),
                id_evento_cassandra=cass["id_evento"],
                pasos_completados=list(saga.doc["pasos"]),
            )
        )
    except Exception as exc:
        return compensar(saga, redis, cql=cql, error=exc)


def reasignar(redis, db, neo, datos, inyector=None):
    saga, res = _inicio(db, "REASIGNACION", datos)
    if res is not None:
        return res
    rescate = f"VIAJE-RESCATE-{uuid5(NAMESPACE_URL,saga.id).hex}"
    saga.guardar(viaje_rescate=rescate)
    try:
        viejo = datos["id_viaje_averiado"]
        veh = datos["patente_reemplazo"]
        cond = datos["conductor_reemplazo"]
        saga.bloquear(
            [
                f"viaje:{viejo}",
                f"viaje:{rescate}",
                f"vehiculo:{veh}",
                f"conductor:{cond}",
            ]
        )
        original = db.viajes.find_one({"_id": viejo, "estado": "EN_CURSO"})
        if not original:
            raise ValueError("Viaje original no activo")
        patente = original.get("vehiculo_patente", original.get("id_vehiculo"))
        if datos["patente_averiada"] != patente:
            raise ValueError("Patente de avería ajena al viaje")
        saga.bloquear([f"vehiculo:{patente}"])
        inicio, fin = intervalo(
            dict(
                inicio_planificado=saga.doc["fecha_inicio"],
                fin_planificado=max(
                    utc(
                        original.get("fin_planificado") or ahora() + timedelta(hours=2)
                    ),
                    ahora() + timedelta(minutes=1),
                ),
            )
        )
        validar_disponibilidad(db, veh, cond, inicio, fin)
        anteriores = list(db.asignaciones.find({"viaje_id": viejo, "estado": "ACTIVA"}))
        if not anteriores:
            raise ValueError("No hay paquetes pendientes")
        paquetes = [a["paquete_codigo"] for a in anteriores]
        saga.bloquear([f"paquete:{p}" for p in paquetes])
        if any(not db.paquetes.find_one({"_id": p}) for p in paquetes):
            raise ValueError("Paquete inexistente")
        reservas = [f"reserva:vehiculo:{veh}", f"reserva:conductor:{cond}"]
        saga.guardar(reservas_redis=reservas)
        _guardar_proyecciones(
            saga,
            redis,
            [
                (f"vehiculo:{patente}:estado", ["estado", "motivo"]),
                (f"vehiculo:{veh}:estado", ["estado", "viaje_id"]),
            ],
        )
        saga.paso(
            "CU05_REDIS_RESERVA",
            lambda: [_reserva(redis, k, saga) for k in reservas],
            inyector,
        )
        destinos = list(dict.fromkeys(a["punto_fin_id"] for a in anteriores))
        grafo = saga.paso(
            "CU05_NEO4J",
            lambda: vincular_rescate_neo4j(
                neo, viejo, rescate, datos["id_punto_averia"], destinos
            ),
            inyector,
        )
        saga.guardar(grafo=grafo)
        nuevas = [f"ASIG-{rescate}-{p}" for p in paquetes]
        for col, ids in [
            ("viajes", [viejo, rescate]),
            ("asignaciones", [a["_id"] for a in anteriores] + nuevas),
            ("paquetes", paquetes),
            ("vehiculos", [patente, veh]),
            ("conductores", [cond]),
        ]:
            saga.snapshot(col, ids)
        usuario = datos.get("creada_por_usuario_id") or original.get(
            "planificado_por_usuario_id"
        )
        if not usuario or not db.usuarios.find_one({"_id": usuario}):
            raise ValueError("Falta usuario coordinador existente")

        def negocio():
            for a, nueva in zip(anteriores, nuevas):
                p = a["paquete_codigo"]
                saga.cambiar(
                    "asignaciones",
                    a["_id"],
                    dict(
                        estado="INTERRUMPIDA",
                        fecha_cierre=inicio,
                        motivo="AVERIA_MECANICA_VEHICULO",
                        saga_reasignacion=saga.id,
                    ),
                )
                if inyector:
                    inyector.verificar("CU05_PAQUETES")
                saga.cambiar(
                    "asignaciones",
                    nueva,
                    dict(
                        viaje_id=rescate,
                        paquete_codigo=p,
                        punto_inicio_id=datos["id_punto_averia"],
                        punto_fin_id=a["punto_fin_id"],
                        estado="ACTIVA",
                        asignacion_origen_id=a["_id"],
                        fecha_asignacion=inicio,
                        creada_por_usuario_id=usuario,
                    ),
                )
                saga.cambiar("paquetes", p, dict(viaje_actual_id=rescate))
            saga.cambiar(
                "viajes",
                viejo,
                dict(
                    estado="INTERRUMPIDO_AVERIA",
                    fecha_interrupcion=inicio,
                    punto_interrupcion=datos["id_punto_averia"],
                ),
            )
            saga.cambiar(
                "viajes",
                rescate,
                dict(
                    tipo="RESCATE",
                    estado="EN_CURSO",
                    viaje_origen_id=viejo,
                    ruta_id=grafo["ruta_id"],
                    id_ruta=grafo["ruta_id"],
                    vehiculo_patente=veh,
                    id_vehiculo=veh,
                    conductor_id=cond,
                    id_conductor=cond,
                    planificado_por_usuario_id=usuario,
                    inicio_planificado=inicio,
                    fin_planificado=fin,
                    fecha_inicio=inicio,
                    paquetes=paquetes,
                    paradas=paradas_planificadas(grafo["recorrido"], {}, inicio, fin),
                    entregas_completadas=0,
                    entregas_pendientes=len(paquetes),
                    demora_acumulada_min=0,
                ),
            )
            saga.cambiar("vehiculos", patente, dict(estado="AVERIADO"))
            saga.cambiar(
                "vehiculos", veh, dict(estado="EN_VIAJE", viaje_actual_id=rescate)
            )
            saga.cambiar(
                "conductores", cond, dict(estado="ASIGNADO", viaje_actual_id=rescate)
            )

        saga.paso("CU05_MONGO", negocio, inyector)

        def proyeccion():
            for k in reservas:
                _reserva(redis, k, saga)
            _proyectar(
                saga,
                redis,
                f"vehiculo:{patente}:estado",
                dict(estado="AVERIADO", motivo="AVERIA_MECANICA_EN_RUTA"),
            )
            _proyectar(
                saga,
                redis,
                f"vehiculo:{veh}:estado",
                dict(estado="EN_VIAJE", viaje_id=rescate),
            )

        saga.paso("CU05_REDIS_CONFIRM", proyeccion, inyector)
        return saga.completar(
            dict(
                exito=True,
                saga_id=saga.id,
                id_viaje_averiado=viejo,
                id_viaje_rescate=rescate,
                patente_averiada=patente,
                patente_reemplazo=veh,
                conductor_reemplazo=cond,
                total_paquetes=len(paquetes),
                paquetes_reasignados=paquetes,
                pasos_completados=list(saga.doc["pasos"]),
            )
        )
    except Exception as exc:
        return compensar(saga, redis, neo, error=exc)
