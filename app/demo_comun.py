"""Fixtures completas y exclusivas por ejecución; nunca reinicia datos existentes."""

from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


def comprobar(condicion, mensaje):
    if not condicion:
        raise RuntimeError(mensaje)


@contextmanager
def motores():
    from app.conexiones import (
        conectar_mongodb,
        conectar_cassandra,
        conectar_redis,
        conectar_neo4j,
    )

    with ExitStack() as stack:
        mongo = conectar_mongodb()
        stack.callback(mongo.close)
        cluster, cql = conectar_cassandra()
        stack.callback(cluster.shutdown)
        redis = conectar_redis()
        stack.callback(redis.close)
        neo = conectar_neo4j()
        stack.callback(neo.close)
        yield SimpleNamespace(
            mongo=mongo, db=mongo["logistica_flota"], cql=cql, redis=redis, neo=neo
        )


def crear_escenario(e, caso, activo=True, alternativa=True, paquetes=2):
    prefijo = f"DEMO-{caso}-{uuid4().hex[:12]}"
    ident = lambda tipo, i=0: f"{prefijo}-{tipo}-{i}"
    ahora = datetime.now(timezone.utc)
    inicio = ahora - timedelta(minutes=2)
    puntos = [ident("P", i) for i in range(4)]
    vehiculos = [ident("VEH", i) for i in range(3)]
    conductores = [ident("COND", i) for i in range(3)]
    codigos = [ident("PAQ", i) for i in range(paquetes)]
    ruta, viaje = ident("RUT"), ident("VIA") if activo else None
    posiciones = [
        (-34.60, -58.40),
        (-34.61, -58.42),
        (-34.63, -58.45),
        (-34.62, -58.39),
    ]
    for i in range(3):
        contacto = ident("CT", i)
        e.db.contactos.insert_one(
            dict(
                _id=contacto,
                demo_id=prefijo,
                tipo="PERSONA",
                dni=ident("DNI", i),
                nombre="Conductor de demostración",
                apellido=str(i + 1),
            )
        )
        e.db.conductores.insert_one(
            dict(
                _id=conductores[i],
                demo_id=prefijo,
                contacto_id=contacto,
                nro_licencia=ident("LIC", i),
                vencimiento=ahora + timedelta(days=365),
                estado="ASIGNADO" if activo and i == 0 else "DISPONIBLE",
            )
        )
        e.db.vehiculos.insert_one(
            dict(
                _id=vehiculos[i],
                patente=vehiculos[i],
                demo_id=prefijo,
                marca="Flota de prueba",
                modelo="Carga",
                tipo="CAMION",
                estado="EN_VIAJE" if activo and i == 0 else "DISPONIBLE",
            )
        )
    for i, (lat, lon) in enumerate(posiciones):
        e.db.puntos_entrega.insert_one(
            dict(
                _id=puntos[i],
                demo_id=prefijo,
                nombre=f"Parada {i+1}",
                latitud=lat,
                longitud=lon,
            )
        )
    usuario = ident("USR")
    e.db.usuarios.insert_one(
        dict(
            _id=usuario,
            username=usuario,
            contacto_id=ident("CT", 0),
            rol="COORDINADOR",
            estado="ACTIVO",
        )
    )
    e.db.rutas.insert_one(
        dict(
            _id=ruta,
            ruta_id=ruta,
            planificada_por_usuario_id=usuario,
            demo_id=prefijo,
            nombre=f"Ruta de demostración {caso}",
            estado="HABILITADA",
            puntos=[
                dict(orden=i + 1, punto_entrega_id=p) for i, p in enumerate(puntos[:3])
            ],
        )
    )
    with e.neo.session() as s:
        for i, (lat, lon) in enumerate(posiciones):
            s.run(
                "CREATE (:PuntoEntrega {punto_entrega_id:$id,nombre:$nombre,latitud:$lat,longitud:$lon,demo_id:$demo})",
                id=puntos[i],
                nombre=f"Parada {i+1}",
                lat=lat,
                lon=lon,
                demo=prefijo,
            ).consume()
        s.run(
            "CREATE (:Ruta {ruta_id:$id,estado:'HABILITADA',demo_id:$demo})",
            id=ruta,
            demo=prefijo,
        ).consume()
        for i, p in enumerate(puntos[:3]):
            s.run(
                "MATCH (r:Ruta {ruta_id:$r}),(p:PuntoEntrega {punto_entrega_id:$p}) CREATE (r)-[:INCLUYE {orden:$orden}]->(p)",
                r=ruta,
                p=p,
                orden=i + 1,
            ).consume()
        tramos = [(0, 1, 3.8, 8), (1, 2, 5.1, 12)] + (
            [(0, 3, 5.0, 20), (3, 2, 6.0, 18)] if alternativa else []
        )
        for a, b, km, minutos in tramos:
            for x, y in ((a, b), (b, a)):
                s.run(
                    "MATCH (a:PuntoEntrega {punto_entrega_id:$a}),(b:PuntoEntrega {punto_entrega_id:$b}) "
                    "CREATE (a)-[:CONECTA {tramo_id:$t,distancia_km:$km,tiempo_estimado_min:$min,habilitado:true}]->(b)",
                    a=puntos[x],
                    b=puntos[y],
                    t=ident(f"T{x}-{y}"),
                    km=km,
                    min=minutos,
                ).consume()
        if activo:
            s.run(
                "MATCH (r:Ruta {ruta_id:$r}) CREATE (v:Viaje {viaje_id:$v,estado:'EN_CURSO',id_vehiculo:$veh,id_conductor:$cond,demo_id:$demo}) CREATE (v)-[:ASIGNADO_A]->(r)",
                r=ruta,
                v=viaje,
                veh=vehiculos[0],
                cond=conductores[0],
                demo=prefijo,
            ).consume()
    if activo:
        e.db.viajes.insert_one(
            dict(
                _id=viaje,
                demo_id=prefijo,
                ruta_id=ruta,
                id_ruta=ruta,
                vehiculo_patente=vehiculos[0],
                id_vehiculo=vehiculos[0],
                conductor_id=conductores[0],
                id_conductor=conductores[0],
                estado="EN_CURSO",
                planificado_por_usuario_id=usuario,
                paquetes=codigos,
                inicio_planificado=inicio,
                fin_planificado=ahora + timedelta(hours=2),
                fecha_inicio=inicio,
                paradas=[
                    dict(
                        orden=i + 1,
                        punto_entrega_id=p,
                        hora_planificada=ahora + timedelta(minutes=10 * i),
                        estado="PENDIENTE",
                    )
                    for i, p in enumerate(puntos[:3])
                ],
            )
        )
        e.redis.set(f"reserva:vehiculo:{vehiculos[0]}", viaje)
        e.redis.set(f"reserva:conductor:{conductores[0]}", viaje)
        e.redis.hset(
            f"vehiculo:{vehiculos[0]}:estado",
            mapping=dict(
                viaje_id=viaje,
                estado="EN_RUTA",
                latitud=-34.6,
                longitud=-58.4,
                velocidad=40.0,
                fecha_hora_ms=int(inicio.timestamp() * 1000),
            ),
        )
        e.redis.hset(
            f"viaje:{viaje}:progreso",
            mapping=dict(entregas_completadas=0, entregas_pendientes=paquetes),
        )
    for i, codigo in enumerate(codigos):
        e.db.paquetes.insert_one(
            dict(
                _id=codigo,
                codigo_seguimiento=codigo,
                demo_id=prefijo,
                remitente_id=ident("CT", 0),
                destinatario_id=ident("CT", 1),
                punto_entrega_id=puntos[2],
                fecha_registro=inicio,
                estado="EN_TRANSITO" if activo else "PENDIENTE",
            )
        )
        if activo:
            e.db.asignaciones.insert_one(
                dict(
                    _id=ident("ASIG", i),
                    demo_id=prefijo,
                    viaje_id=viaje,
                    paquete_codigo=codigo,
                    punto_inicio_id=puntos[0],
                    punto_fin_id=puntos[2],
                    fecha_asignacion=inicio,
                    estado="ACTIVA",
                )
            )
        e.redis.hset(
            f"paquete:{codigo}:estado",
            mapping=dict(
                estado="EN_TRANSITO" if activo else "PENDIENTE", viaje_id=viaje or ""
            ),
        )
    return dict(
        demo_id=prefijo,
        ruta=ruta,
        viaje=viaje,
        vehiculos=vehiculos,
        conductores=conductores,
        paquetes=codigos,
        puntos=puntos,
        tramo=f"{prefijo}-T0-1-0",
    )


def emitir(
    f,
    velocidad=40.0,
    latitud=-34.601,
    longitud=-58.401,
    instante=None,
    viaje=None,
    vehiculo=None,
):
    from app.telemetria import registrar_telemetria

    datos = dict(
        id_evento=str(uuid4()),
        viaje_id=viaje or f["viaje"],
        vehiculo_patente=vehiculo or f["vehiculos"][0],
        fecha_hora=(instante or datetime.now(timezone.utc)).isoformat(),
        latitud=latitud,
        longitud=longitud,
        velocidad=float(velocidad),
        estado_vehiculo="EN_MOVIMIENTO" if velocidad else "DETENIDO",
    )
    ok, resultado = registrar_telemetria(datos)
    comprobar(ok, f"Falló la ingesta real de la fixture: {resultado}")
    return datos, resultado


def guardar_resultado(caso, escenario, fixture, resultado, verificaciones):
    reporte = dict(
        caso=caso,
        escenario=escenario,
        fixture=fixture,
        resultado=resultado,
        verificaciones=verificaciones,
        verificado=True,
    )
    carpeta = Path("resultados_menus")
    carpeta.mkdir(exist_ok=True)
    contenido = json.dumps(reporte, ensure_ascii=False, indent=2, default=str) + "\n"
    (carpeta / f'{fixture["demo_id"]}.json').write_text(contenido)
    (carpeta / f"ultimo_{caso}.json").write_text(contenido)
    print(contenido)
    if fixture.get("paquetes"):
        print("Código para CU-08:", fixture["paquetes"][0])
    return reporte


def valor_redis(cliente, clave):
    """Lectura de las estructuras de texto que usa el TPO (sin DUMP binario)."""
    tipo = cliente.type(clave)
    if tipo == "hash":
        return dict(tipo=tipo, valor=cliente.hgetall(clave))
    if tipo == "string":
        return dict(tipo=tipo, valor=cliente.get(clave))
    if tipo == "none":
        return None
    if tipo == "set":
        return dict(tipo=tipo, valor=sorted(cliente.smembers(clave)))
    if tipo == "list":
        return dict(tipo=tipo, valor=cliente.lrange(clave, 0, -1))
    if tipo == "zset":
        return dict(tipo=tipo, valor=cliente.zrange(clave, 0, -1, withscores=True))
    return dict(tipo=tipo)  # Esta demo no escribe estructuras de otros tipos.
